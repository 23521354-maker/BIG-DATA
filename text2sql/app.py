from decimal import Decimal
"""VN30 Text-to-SQL UI.   Run:  streamlit run app.py     (API key can be typed in the sidebar; it is never written to disk)"""
import os, sys, json, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import pandas as pd
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t2s, grade, rag_ui

st.set_page_config(page_title="VN30 Text-to-SQL", page_icon="📊", layout="wide")

# ---------- cached resources ----------
def new_con():
    """one Trino connection per thread/request: queries run on the lakehouse (Iceberg tables on MinIO)"""
    return t2s.connect()

@st.cache_resource(show_spinner=False)
def default_key():
    """the key from the shell or text2sql/.env, captured once before anything typed in the sidebar can overwrite it"""
    return os.environ.get("OPENAI_API_KEY", "")
DEFAULT_KEY = default_key()

@st.cache_resource(show_spinner=False)
def get_system():
    return t2s.system_prompt(new_con())

def q_df(sql):
    r = new_con().execute(sql)
    return pd.DataFrame(r.fetchall(), columns=[d[0] for d in r.description])

# ---------- helpers ----------
def norm(rows):
    c = lambda v: round(float(v), 2) if isinstance(v, (float, Decimal)) else v
    return sorted(tuple(str(c(v)) for v in r) for r in rows)

def lenient(pred, gold):
    if len(pred) != len(gold): return False
    P = [set(r) for r in norm(pred)]; used = set()
    for g in norm(gold):
        for k, p in enumerate(P):
            if k not in used and set(g) <= p: used.add(k); break
        else: return False
    return True

def run_item(g, backend, model, sysmsg):
    cur = new_con()                          # one connection per thread; gold answers are frozen in the question file (field "gold")
    t0 = time.time()
    if g["sql"] is None:                     # unanswerable / unsafe → pass if declined, blocked or empty
        r = t2s.ask(g["q"], cur, backend, model, system=sysmsg)
        ok = (r["error"] is not None and any(k in r["error"] for k in ("declined", "only SELECT", "forbidden"))) or (r["error"] is None and len(r["rows"]) == 0)
        return dict(id=g["id"], q=g["q"], kind="unanswerable", ok=ok, lenient_ok=ok, executed=r["error"] is None, error=r["error"], sql=r["sql"], gold_sql=None, pred_rows=len(r["rows"]), gold_rows=0, attempts=r["attempts"], sec=round(time.time() - t0, 1))
    gold = g["gold"]
    r = t2s.ask(g["q"], cur, backend, model, system=sysmsg)
    ok = r["error"] is None and grade.strict(r["rows"], gold)
    lk = r["error"] is None and (ok or grade.lenient(r["rows"], gold))
    return dict(id=g["id"], q=g["q"], kind="answerable", ok=ok, lenient_ok=lk, executed=r["error"] is None, error=r["error"], sql=r["sql"], gold_sql=g["sql"], pred_rows=len(r["rows"]), gold_rows=len(gold), attempts=r["attempts"], sec=round(time.time() - t0, 1))

def show_chart(df, mode):
    if df.empty or df.shape[1] < 2 or mode == "None": return
    num = [c for c in df.columns[1:] if pd.api.types.is_numeric_dtype(df[c])]
    if not num: return
    d = df.set_index(df.columns[0])[num]
    yearish = str(df.columns[0]).lower() in ("fiscal_year", "year", "năm") or (pd.api.types.is_integer_dtype(df.iloc[:, 0]) and df.iloc[:, 0].between(1990, 2100).all())
    kind = mode if mode != "Auto" else ("Line" if yearish else "Bar")
    if len(d) > 40: d = d.head(40)
    d.index = d.index.astype(str)
    (st.line_chart if kind == "Line" else st.bar_chart)(d)

# ---------- sidebar ----------
st.sidebar.title("⚙️ Settings")
backend = st.sidebar.selectbox("Backend", ["openai", "ollama", "rules"], help="openai = any OpenAI-compatible API (DeepSeek). rules = no-LLM baseline.")
if backend == "openai":
    _choice = st.sidebar.selectbox("Model", ["deepseek-flash", "deepseek-v4-pro", "Other…"])
    model = st.sidebar.text_input("Custom model name") if _choice == "Other…" else _choice
elif backend == "ollama":
    model = st.sidebar.text_input("Model", "qwen2.5-coder:7b")
else:
    model = "rules"
if backend == "openai":
    base = st.sidebar.text_input("Base URL", os.environ.get("OPENAI_BASE_URL", "https://api.deepseek.com/v1"))
    key = st.sidebar.text_input("API key", type="password", value="", placeholder="(empty = default key from .env)" if DEFAULT_KEY else "(or put it in text2sql/.env)")
    os.environ["OPENAI_BASE_URL"] = base
    if key: os.environ["OPENAI_API_KEY"] = key                              # a typed key replaces the default for this session ...
    elif DEFAULT_KEY: os.environ["OPENAI_API_KEY"] = DEFAULT_KEY            # ... and clearing the box rolls back to the default
    else: os.environ.pop("OPENAI_API_KEY", None)
    if not os.environ.get("OPENAI_API_KEY"): st.sidebar.warning("No API key set — type it above or put it in text2sql/.env (see .env.example).")
    elif not key: st.sidebar.caption("Using the default key from the environment / .env.")
st.sidebar.caption("Query engine: Trino (lakehouse on MinIO). Needs the cluster running and `lakehouse\\scripts\\ops\\port-forward.ps1 trino`.")
workers = st.sidebar.slider("Parallel requests (Evaluate tab)", 1, 16, 6)
st.sidebar.caption("A key typed here lives only in memory. The default key, if any, comes from text2sql/.env (git-ignored).")

try:
    new_con().execute("SELECT 1").fetchall()
except Exception as e:
    st.error(f"Cannot reach Trino ({type(e).__name__}). Start the cluster (lakehouse\\scripts\\ops\\mode-full.ps1), run lakehouse\\scripts\\ops\\port-forward.ps1 trino in another window, then reload this page.")
    st.stop()
sysmsg = None if backend == "rules" else get_system()

st.title("📊 VN30 Annual-Report Financial Indicators — Text-to-SQL")
tab_chat, tab_eval, tab_data = st.tabs(["💬 Ask", "🧪 Evaluate", "🗂️ Data coverage"])

# ---------- Ask (numbers via SQL, report text via search; routed automatically, see rag_ui.py) ----------
with tab_chat:
    rag_ui.render_chat(new_con, backend, model, sysmsg, show_chart)

# ---------- Evaluate ----------
with tab_eval:
    sets = [f for f in os.listdir(t2s.HERE) if f.startswith("golden") and f.endswith(".json")]
    c1, c2 = st.columns([2, 1])
    gset = c1.selectbox("Question set", sorted(sets), help="golden.json = dev set (already seen while tuning). golden_heldout.json = run once, do not tune on it.")
    go = c2.button("▶ Run evaluation", type="primary", width="stretch")
    if go:
        G = json.load(open(os.path.join(t2s.HERE, gset), encoding="utf-8")); res = {}
        bar = st.progress(0.0, text="Starting…"); live = st.empty(); t0 = time.time()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(run_item, g, backend, model, sysmsg): g for g in G}
            for f in as_completed(futs):
                g = futs[f]
                try: x = f.result()
                except Exception as e: x = dict(id=g["id"], q=g["q"], kind="answerable" if g["sql"] else "unanswerable", ok=False, lenient_ok=False, executed=False, error=f"{type(e).__name__}: {e}", sql=None, gold_sql=g["sql"], pred_rows=0, gold_rows=0, attempts=0, sec=0)
                res[x["id"]] = x; bar.progress(len(res) / len(G), text=f"{len(res)}/{len(G)} done · {time.time() - t0:.0f}s")
                live.dataframe(pd.DataFrame(sorted(res.values(), key=lambda z: z["id"]))[["id", "q", "ok", "lenient_ok", "executed", "sec"]], width="stretch", hide_index=True)
        out = sorted(res.values(), key=lambda z: z["id"]); st.session_state.last_eval = (gset, backend, model, out, time.time() - t0)
        fn = os.path.join(t2s.HERE, f"eval_{os.path.splitext(gset)[0]}_{backend}_{model.replace(':', '-').replace('/', '-')}_trino.json")
        json.dump(out, open(fn, "w", encoding="utf-8"), ensure_ascii=False, indent=1); bar.empty(); live.empty()
    if "last_eval" in st.session_state:
        gset, be, mo, out, secs = st.session_state.last_eval; n = len(out)
        st.subheader(f"{gset} · {be}/{mo} · {secs:.0f}s")
        m = st.columns(4)
        m[0].metric("Strict", f"{sum(x['ok'] for x in out)}/{n}"); m[1].metric("Lenient (extra columns OK)", f"{sum(x['lenient_ok'] for x in out)}/{n}")
        m[2].metric("Executable", f"{sum(x['executed'] for x in out)}/{n}")
        un = [x for x in out if x["kind"] == "unanswerable"]; m[3].metric("Unanswerable handled", f"{sum(x['ok'] for x in un)}/{len(un)}")
        st.caption("Strict = identical rows. Lenient = same rows, extra columns allowed. Unanswerable items pass if the system declines, is blocked, or returns nothing.")
        bad = [x for x in out if not x["lenient_ok"]]
        st.markdown(f"**Failures ({len(bad)})**" if bad else "**No failures 🎉**")
        for x in bad:
            with st.expander(f"#{x['id']} · {x['q']}"):
                st.write(f"error: `{x['error']}`" if x["error"] else f"wrong result (pred rows {x['pred_rows']}, gold rows {x['gold_rows']})")
                st.markdown("Predicted SQL"); st.code(x["sql"] or "(none)", language="sql")
                if x["gold_sql"]: st.markdown("Gold SQL"); st.code(x["gold_sql"], language="sql")
        st.download_button("Download results JSON", json.dumps(out, ensure_ascii=False, indent=1).encode("utf-8"), "eval_results.json")

# ---------- Data coverage ----------
with tab_data:
    st.caption("How many metrics each (ticker, year) has in `financial_indicators`, and how many text chunks in `text_chunks`. Zeros are real gaps.")
    a = q_df("SELECT ticker, fiscal_year, COUNT(DISTINCT metric) n FROM financial_indicators GROUP BY 1,2").pivot(index="ticker", columns="fiscal_year", values="n").fillna(0).astype(int)
    b = q_df("SELECT ticker, fiscal_year, COUNT(*) n FROM text_chunks GROUP BY 1,2").pivot(index="ticker", columns="fiscal_year", values="n").reindex(a.index).fillna(0).astype(int)
    c1, c2 = st.columns(2)
    c1.markdown("**Distinct metrics per (ticker, year)**"); c1.dataframe(a, width="stretch")
    c2.markdown("**Text chunks per (ticker, year)**"); c2.dataframe(b, width="stretch")
    miss = [(t, int(y)) for t in b.index for y in b.columns if b.loc[t, y] == 0]
    st.markdown(f"**Missing text chunks: {len(miss)} (ticker, year) pairs**"); st.write(", ".join(f"{t}-{y}" for t, y in miss) or "none")
