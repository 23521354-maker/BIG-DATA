"""Document Q&A over the Silver `text_chunks` table (annual-report text).

Retrieval: keyword scoring done in SQL on Trino. Then an LLM answers from the retrieved excerpts only, with citations like [VCB 2023 p.12].
Ask from the command line (needs the Trino port-forward and an API key):
    python rag.py ask "VCB định hướng chiến lược gì năm 2023?" --backend openai --llm deepseek-flash
"""
import os, re, sys, argparse, unicodedata
import t2s

COLS = "chunk_id, ticker, fiscal_year, page, text"

def nfc(s): return unicodedata.normalize("NFC", s or "")


# ---------------------------------------------------------------- filters from the question
ALIAS = {"vietcombank": "VCB", "vietinbank": "CTG", "techcombank": "TCB", "hòa phát": "HPG", "hoà phát": "HPG", "vinamilk": "VNM", "vingroup": "VIC",
         "vinhomes": "VHM", "thế giới di động": "MWG", "petrolimex": "PLX", "sacombank": "STB", "vpbank": "VPB", "mb bank": "MBB", "tpbank": "TPB",
         "hdbank": "HDB", "bảo việt": "BVH", "vietjet": "VJC", "masan": "MSN", "sabeco": "SAB", "đức giang": "DGC", "becamex": "BCM", "pv gas": "GAS"}

def detect_filters(q, companies):
    """companies: [(ticker, company_name)] -> (tickers, years) mentioned in the question."""
    ql, known, tk = nfc(q).lower(), {c[0] for c in companies}, set()
    for t, name in companies:
        if re.search(rf"(?<![a-z0-9]){re.escape(t.lower())}(?![a-z0-9])", ql) or (name and len(name) > 3 and name.lower() in ql): tk.add(t)
    for a, t in ALIAS.items():
        if a in ql and t in known: tk.add(t)
    return sorted(tk), sorted({int(y) for y in re.findall(r"(?<!\d)(20[12]\d)(?!\d)", ql)})


# ---------------------------------------------------------------- keyword retrieval
STOP = set("của và là có các những được trong cho với một năm bao nhiêu nào gì như thế nào để khi này đó về từ theo ở tại ra không bị cũng hay hoặc nhất "
           "công ty ngân hàng tập đoàn báo cáo the of and is in for what how which are was were did does".split())

def _lit(s): return "'" + s.replace("'", "''") + "'"

def kw_terms(q, drop=()):
    ws, uni, bi, prev = re.findall(r"[^\W_]+", nfc(q).lower()), [], [], None
    for w in ws:
        if w in STOP or w in drop or re.fullmatch(r"20\d\d", w) or len(w) < 2: prev = None; continue
        uni.append(w)
        if prev: bi.append(prev + " " + w)
        prev = w
    bi, uni = list(dict.fromkeys(bi))[:8], [u for u in dict.fromkeys(uni) if len(u) >= 3][:12]
    return bi, ([] if len(bi) >= 2 else uni)       # single syllables match everywhere: use them only when there are too few word pairs

def _hit(r, score, mode): return {"chunk_id": r[0], "ticker": r[1], "year": int(r[2]), "page": int(r[3]), "text": nfc(r[4]), "score": float(score), "mode": mode}

def search_keyword(con, q, tickers=(), years=(), k=6, pool=60):
    bi, uni = kw_terms(q, {t.lower() for t in tickers})
    if not bi and not uni: return []
    body = "lower(normalize(text, NFC))"
    sc = " + ".join([f"3*CASE WHEN {body} LIKE {_lit('%' + b + '%')} THEN 1 ELSE 0 END" for b in bi] +
                    [f"CASE WHEN {body} LIKE {_lit('%' + u + '%')} THEN 1 ELSE 0 END" for u in uni])
    where = []
    if tickers: where.append("ticker IN (" + ",".join(_lit(t) for t in tickers) + ")")
    if years: where.append("fiscal_year IN (" + ",".join(str(int(y)) for y in years) + ")")
    sql = (f"SELECT {COLS}, sc FROM (SELECT {COLS}, ({sc}) AS sc FROM text_chunks" + (" WHERE " + " AND ".join(where) if where else "") +
           f") t WHERE sc > 0 ORDER BY sc DESC, chunk_id LIMIT {int(pool)}")
    rows = con.execute(sql).fetchall()
    def tf(r):
        t = nfc(r[4]).lower()
        return r[5] + sum(t.count(x) for x in bi) * 0.05 + sum(t.count(x) for x in uni) * 0.01
    return [_hit(r, tf(r), "keyword") for r in sorted(rows, key=tf, reverse=True)[:k]]


def search(con, q, tickers=(), years=(), k=6):
    return search_keyword(con, q, tickers, years, k)


# ---------------------------------------------------------------- answer
SYS = ("You answer questions about Vietnamese listed companies using ONLY the excerpts from their annual reports given below. "
       "Excerpts may contain OCR noise and table fragments. Cite every claim as [TICKER year p.PAGE]. "
       "If the excerpts do not contain the answer, say so plainly instead of guessing. Answer in the language of the question. Be concise.")

def build_prompt(q, hits):
    return "EXCERPTS:\n\n" + "\n\n".join(f"[{h['ticker']} {h['year']} p.{h['page']}]\n{h['text'][:1200]}" for h in hits) + f"\n\nQUESTION: {q}"

def answer(q, hits, backend, model):
    """-> (answer text, approx tokens sent). Only the top-k excerpts go to the LLM, so the cost per question stays small."""
    if not hits: return "No matching text found in the annual reports.", 0
    user = build_prompt(q, hits)
    return t2s.llm(backend, model, SYS, user), (len(SYS) + len(user)) // 3


ROUTE_SYS = ("Classify a question about Vietnamese listed companies. Reply with exactly one word. "
             "SQL = it asks for numbers that sit in a financial-indicators table (revenue, profit, assets, equity, ROE, ROA, NPL, loans, deposits, dividends, EPS, employees, rankings, top-N, trends). "
             "TEXT = it asks about narrative content of the annual report (strategy, risks, plans, explanations, events, policies, people). "
             "BOTH = it needs a number and an explanation from the text.")

def route_heuristic(q):
    ql = nfc(q).lower()
    return "SQL" if any(p in ql for ps in t2s.SYN.values() for p in ps) else "TEXT"

def route(q, backend, model):
    """-> 'SQL' | 'TEXT' | 'BOTH'. One tiny LLM call (about 150 tokens); falls back to keyword rules when there is no LLM or it fails."""
    if backend == "rules": return route_heuristic(q)
    try: out = t2s.llm(backend, model, ROUTE_SYS, q).strip().upper()
    except Exception: return route_heuristic(q)
    return "BOTH" if "BOTH" in out else "TEXT" if "TEXT" in out else "SQL" if "SQL" in out else route_heuristic(q)


def companies(con):
    return [(r[0], r[1]) for r in con.execute("SELECT ticker, company_name FROM companies").fetchall()]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["ask"]); ap.add_argument("question")
    ap.add_argument("--backend", default="openai"); ap.add_argument("--llm", default="deepseek-flash"); ap.add_argument("--k", type=int, default=6)
    a = ap.parse_args()
    con = t2s.connect(); tk, yr = detect_filters(a.question, companies(con)); print("filters:", tk, yr)
    hits = search(con, a.question, tk, yr, a.k)
    for h in hits: print(f"  [{h['ticker']} {h['year']} p.{h['page']}] score={h['score']:.3f} {h['text'][:90]!r}")
    if a.backend != "rules": txt, tok = answer(a.question, hits, a.backend, a.llm); print(f"\n{txt}\n\n(~{tok} tokens sent to the LLM)")
