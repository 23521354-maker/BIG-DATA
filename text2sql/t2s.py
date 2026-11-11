"""Text-to-SQL over the VN30 tables. Engines: duckdb (local Delta files, default) | trino (lakehouse: Iceberg on MinIO, schema vn30_silver).
  python t2s.py "Lợi nhuận sau thuế của VCB năm 2024?" --backend ollama --model qwen2.5-coder:7b
Backends: ollama (http://localhost:11434) | openai (OPENAI_BASE_URL, OPENAI_API_KEY; DeepSeek/OpenAI-compatible) | rules (no LLM)
"""
import os, re, sys, json, argparse, urllib.request
import duckdb
from deltalake import DeltaTable
HERE = os.path.dirname(os.path.abspath(__file__)); DELTA = os.environ.get("VN30_DELTA", os.path.join(os.path.dirname(HERE), "delta"))
TABLES = ("financial_indicators", "text_chunks", "companies", "metric_catalog")

class _TrinoResult:
    def __init__(self, rows, description): self._rows = rows; self.description = description
    def fetchall(self): return self._rows

class TrinoConn:
    """Minimal DuckDB-like wrapper: execute(sql) -> object with .description and .fetchall(). Read-only use only (the validator in ask() allows SELECT/WITH)."""
    dialect = "trino"
    def __init__(self, host=None, port=None, user="admin", catalog="iceberg", schema="vn30_silver"):
        import trino
        self._c = trino.dbapi.connect(host=host or os.environ.get("T2S_TRINO_HOST", "localhost"), port=int(port or os.environ.get("T2S_TRINO_PORT", "8080")),
                                      user=user, catalog=catalog, schema=schema, http_scheme="http")
    def execute(self, sql):
        cur = self._c.cursor(); cur.execute(sql); rows = cur.fetchall()   # fetch first: the column list is only known after the first page
        return _TrinoResult(rows, cur.description)

def connect_trino(): return TrinoConn()

def connect(engine=None):
    engine = engine or os.environ.get("T2S_ENGINE", "duckdb")
    if engine == "trino": return connect_trino()
    con = duckdb.connect()
    for t in TABLES: con.register(t, DeltaTable(os.path.join(DELTA, t)).to_pyarrow_table())
    con.execute("SET enable_external_access=false")
    return con

def system_prompt(con):
    trino = getattr(con, "dialect", "duckdb") == "trino"
    eng = "Trino" if trino else "DuckDB"
    search = "lower(text) LIKE '%keyword%' with a lower-case keyword" if trino else "text ILIKE '%keyword%'"
    notes = ("TRINO SQL NOTES: no ILIKE (use lower(col) LIKE ...) and no :: casts (use CAST(x AS type)); dividing two integers truncates, so CAST(x AS DOUBLE) first; "
             "tables are already in the default schema, never prefix a table name.\n") if trino else ""
    mc = con.execute("select metric, name_vi, unit, applies_to from metric_catalog").fetchall()
    co = con.execute("select ticker, company_name, sector, is_bank from companies order by 1").fetchall()
    return f"""You translate Vietnamese or English questions about VN30 annual-report indicators into ONE {eng} SQL query. Output only the SQL.
TABLES
financial_indicators(ticker, fiscal_year INT, metric, value, unit, value_bn_vnd, value_vnd, scope, source_page, method, source, confidence, needs_review BOOL, value_prior, cross_year_ok, swapped, conflict, value_extracted, cafef_value, cafef_status, cafef_url, yoy_flag, raw_row)
  one row per (ticker, fiscal_year, metric); fiscal_year 2020-2025. source: 'bctn' (extracted from annual report), 'cafef' (verified from CafeF), 'derived' (ROE/ROA computed).
  Money metrics: use value_bn_vnd (VND billions = tỷ đồng). Ratios and counts (roe, roa, eps, employees, dividend, npl_ratio, car): use value (ratios in %).
  needs_review=false means a trusted record; confidence is 0..1. employees, dividend, npl_ratio, car are LOW-reliability (OCR/regex, sparse): do NOT filter on needs_review unless the user asks, but also SELECT needs_review for those metrics so the reader sees it.
text_chunks(chunk_id, ticker, fiscal_year, source_file, page, chunk_index, text_source, n_chars, text) - report text; search with {search}.
companies(ticker, company_name, sector, is_bank) ; metric_catalog(metric, name_en, name_vi, unit, kind, applies_to)
METRICS (metric | Vietnamese | unit | applies_to): {'; '.join(f'{a} | {b} | {c} | {d}' for a, b, c, d in mc)}
COMPANIES (ticker=name, sector): {'; '.join(f'{a}={b} ({c}{", bank" if d else ""})' for a, b, c, d in co)}
RULES: banks have no net_revenue (use net_interest_income); filter by ticker/fiscal_year/metric exactly as named; join companies for sector, bank or company-name questions; use only SELECT (no DDL/DML); no trailing explanation. If the question cannot be answered from these tables (stock prices, forecasts, companies or years not in the data) or asks to change data, output exactly: -- UNANSWERABLE
{notes}EXAMPLES
Q: Tổng tài sản của STB năm 2022?  SQL: SELECT value_bn_vnd FROM financial_indicators WHERE ticker='STB' AND fiscal_year=2022 AND metric='total_assets'
Q: Top 3 ngân hàng có ROA cao nhất năm 2021  SQL: SELECT f.ticker, f.value AS roa FROM financial_indicators f JOIN companies c USING(ticker) WHERE c.is_bank AND f.metric='roa' AND f.fiscal_year=2021 ORDER BY f.value DESC LIMIT 3"""

def extract_sql(txt):
    if "UNANSWERABLE" in txt.upper(): return ""
    m = re.search(r"```(?:sql)?\s*(.*?)```", txt, re.S | re.I); s = (m.group(1) if m else txt).strip()
    m = re.search(r"\b(select|with)\b", s, re.I); s = s[m.start():] if m else s
    return s.strip().rstrip(";").strip()

BAD = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|detach|copy|pragma|install|load|export|import|call|set|truncate|replace|read_csv|read_parquet|read_json|glob|httpfs|merge|grant|revoke|execute|prepare|deallocate)\b", re.I)
def validate(sql):
    s = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql, flags=re.S).strip()
    if ";" in s: raise ValueError("multiple statements")
    if not re.match(r"(select|with)\b", s, re.I): raise ValueError("only SELECT/WITH allowed")
    if BAD.search(re.sub(r"'[^']*'", "''", s)): raise ValueError("forbidden keyword")
    return s

def http_json(url, payload, headers=None):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json", **(headers or {})})
    return json.load(urllib.request.urlopen(req, timeout=180))
def llm(backend, model, system, user):
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    if backend == "ollama":
        return http_json(os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/chat", {"model": model, "messages": msgs, "stream": False, "options": {"temperature": 0}})["message"]["content"]
    base = os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    return http_json(base + "/chat/completions", {"model": model, "messages": msgs, "temperature": 0}, {"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"]})["choices"][0]["message"]["content"]

# ---- no-LLM baseline: template rules for the most common question shapes
SYN = {"net_profit_after_tax": ["lợi nhuận sau thuế", "lợi nhuận ròng", "npat", "net profit"], "net_revenue": ["doanh thu", "revenue"], "total_assets": ["tổng tài sản", "total assets"],
       "equity": ["vốn chủ sở hữu", "equity"], "net_interest_income": ["thu nhập lãi thuần", "nii"], "roe": ["roe"], "roa": ["roa"], "npl_ratio": ["nợ xấu", "npl"],
       "customer_loans": ["cho vay khách hàng"], "customer_deposits": ["tiền gửi khách hàng"], "employees": ["nhân viên", "lao động"], "eps": ["eps"], "car": ["car", "an toàn vốn"]}
def rules_sql(q, con):
    ql = q.lower(); met = next((m for m, ws in SYN.items() if any(w in ql for w in ws)), None)
    tick = [t for (t,) in con.execute("select ticker from companies").fetchall() if re.search(rf"\b{t}\b", q)]
    yrs = [int(y) for y in re.findall(r"\b(20[12]\d)\b", q)]
    if not met: raise ValueError("rules: metric not recognised")
    col = "value" if met in ("roe", "roa", "npl_ratio", "car", "eps", "employees", "dividend") else "value_bn_vnd"
    top = re.search(r"top\s*(\d+)", ql) or (re.search(r"(cao nhất|lớn nhất)", ql) and re.match("", ""))
    if tick and len(yrs) == 1:
        return f"SELECT ticker, fiscal_year, {col} FROM financial_indicators WHERE ticker IN ({','.join(repr(t) for t in tick)}) AND fiscal_year={yrs[0]} AND metric='{met}' ORDER BY ticker"
    if tick:
        return f"SELECT ticker, fiscal_year, {col} FROM financial_indicators WHERE ticker IN ({','.join(repr(t) for t in tick)}) AND metric='{met}' ORDER BY ticker, fiscal_year"
    if top and len(yrs) == 1:
        n = int(top.group(1)) if top.groups() and top.group(1) and top.group(1).isdigit() else 1
        j = "JOIN companies c USING(ticker) WHERE c.is_bank AND " if "ngân hàng" in ql else "WHERE "
        return f"SELECT ticker, {col} FROM financial_indicators f {j}metric='{met}' AND fiscal_year={yrs[0]} ORDER BY {col} DESC LIMIT {n}"
    raise ValueError("rules: question shape not supported")

def ask(question, con, backend="rules", model="qwen2.5-coder:7b", retries=1, system=None):
    out = {"question": question, "sql": None, "cols": [], "rows": [], "error": None, "attempts": 0}
    if backend == "rules":
        try: sql = rules_sql(question, con)
        except Exception as e: out["error"] = str(e); return out
    else:
        system = system or system_prompt(con); user = question; sql = None
    last = None
    for k in range(retries + 1 if backend != "rules" else 1):
        out["attempts"] = k + 1
        try:
            if backend != "rules":
                sql = extract_sql(llm(backend, model, system, user))
                if sql == "": out["error"] = "declined: question not answerable from the data"; out["sql"] = None; return out
            clean = validate(sql); out["sql"] = clean
            cur = con.execute(f"SELECT * FROM ({clean}) LIMIT 500"); out["cols"] = [d[0] for d in cur.description]; out["rows"] = cur.fetchall(); out["error"] = None
            return out
        except Exception as e:
            out["error"] = f"{type(e).__name__}: {e}"; out["sql"] = sql
            user = f"{question}\nYour previous SQL failed:\n{sql}\nError: {e}\nReturn a corrected SQL only."
    return out

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("question"); ap.add_argument("--backend", default="rules", choices=["rules", "ollama", "openai"]); ap.add_argument("--model", default="qwen2.5-coder:7b")
    a = ap.parse_args(); r = ask(a.question, connect(), a.backend, a.model)
    print("SQL:", r["sql"]); print("ERROR:" , r["error"]) if r["error"] else [print(r["cols"])] + [print(x) for x in r["rows"][:30]]
