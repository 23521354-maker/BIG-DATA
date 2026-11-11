"""Streamlit Ask tab: one box that routes each question to SQL (numbers), report-text search, or both. Called from app.py."""
import time
import pandas as pd
import streamlit as st
import t2s, rag

CHAT_EXAMPLES = [
    "Lợi nhuận sau thuế của VCB năm 2023 là bao nhiêu?",
    "Top 5 công ty có tổng tài sản lớn nhất năm 2024",
    "ROE trung bình của từng ngân hàng, xếp từ cao xuống thấp",
    "VCB 2023 định hướng chiến lược phát triển như thế nào?",
    "Lợi nhuận sau thuế của VCB năm 2023 là bao nhiêu và ngân hàng nói gì về kết quả đó?",
    "Giá cổ phiếu VNM hôm nay là bao nhiêu?",
]
BAD_SHARE = 0.3    # a report whose chunks rarely contain a common word lost its diacritics (OCR/font problem): good reports sit at 0.65-0.8, bad ones at 0-0.07


@st.cache_data(show_spinner=False, ttl=3600)
def _companies(_new_con):
    return rag.companies(_new_con())


@st.cache_data(show_spinner=False, ttl=3600)
def _quality(_new_con):
    """{(ticker, year): share of chunks that contain a common word}; a (ticker, year) missing from the dict has no text at all."""
    sql = ("SELECT ticker, fiscal_year, AVG(CASE WHEN lower(normalize(text, NFC)) LIKE '% của %' OR lower(text) LIKE '% the %' THEN 1.0 ELSE 0.0 END) "
           "FROM text_chunks GROUP BY 1, 2")
    return {(t, int(y)): float(s) for t, y, s in _new_con().execute(sql).fetchall()}


def _docs_query(new_con, q, k, backend, model):
    """retrieve + answer; never raises (errors go into r['error'])"""
    t0, r = time.time(), {"question": q, "answer": None, "tokens": 0, "hits": [], "error": None, "tickers": [], "years": []}
    try:
        r["tickers"], r["years"] = rag.detect_filters(q, _companies(new_con))
        with st.spinner("Searching the reports…"):
            r["hits"] = rag.search(new_con(), q, r["tickers"], r["years"], k)
        if backend != "rules" and r["hits"]:
            with st.spinner("Writing the answer…"):
                r["answer"], r["tokens"] = rag.answer(q, r["hits"], backend, model)
    except KeyError as e:
        r["error"] = "Missing API key: type it in the sidebar." if "OPENAI_API_KEY" in str(e) else f"KeyError: {e}"
    except Exception as e:
        r["error"] = f"{type(e).__name__}: {e}"
    r["sec"] = round(time.time() - t0, 1)
    return r


def _docs_show(r, qual, backend, title=True):
    flt = ", ".join(r["tickers"] + [str(y) for y in r["years"]]) or "none"
    if title: st.markdown(f"**{r['question']}**  · {r['sec']}s · filters: {flt}")
    else: st.caption(f"Text search · {r['sec']}s · filters: {flt}")
    if r["error"]: st.error(r["error"]); return
    missing = [(t, y) for t in r["tickers"] for y in r["years"] if (t, y) not in qual]
    if missing: st.warning("No text for " + ", ".join(f"{t} {y}" for t, y in missing) + " (that annual report is not in the dataset or has no extracted text).")
    if not r["hits"] and not missing: st.info("Nothing in the reports matches these words. Try other words (the search matches words, not meaning).")
    if r["answer"]: st.markdown(r["answer"]); st.caption(f"≈{r['tokens']:,} tokens sent to the LLM (only the top excerpts, not the whole corpus).")
    weak = sorted({(h["ticker"], h["year"]) for h in r["hits"] if qual.get((h["ticker"], h["year"]), 1) < BAD_SHARE})
    if weak: st.warning("⚠️ Text of " + ", ".join(f"{t} {y}" for t, y in weak) + " lost many Vietnamese diacritics during extraction (OCR/font problem), so retrieval and the answer may be unreliable for it.")
    if r["hits"]:
        with st.expander(f"Sources ({len(r['hits'])} excerpts)", expanded=backend == "rules" or not r["answer"]):
            for h in r["hits"]:
                st.markdown(f"**[{h['ticker']} {h['year']} p.{h['page']}]** · score {h['score']:.3f}")
                st.text(h["text"][:900])


# ---------------------------------------------------------------- tab: Ask (auto route)
def render_chat(new_con, backend, model, sysmsg, show_chart):
    qual = _quality(new_con)
    st.caption("Ask in Vietnamese or English. Each question is routed automatically: **SQL** (numbers: the model writes a read-only query and Trino computes the result from `financial_indicators`), "
               "**TEXT** (what the reports say: written from retrieved excerpts, with page citations) or **BOTH**.")
    cols = st.columns(3)
    for i, ex in enumerate(CHAT_EXAMPLES):
        if cols[i % 3].button(ex, key=f"cex{i}", width="stretch"): st.session_state.cq = ex
    if "cq" not in st.session_state: st.session_state.cq = ""
    q = st.text_input("Ask anything about the VN30 reports", key="cq", placeholder="e.g. Techcombank lãi bao nhiêu năm 2024 và định hướng gì cho 2025?")
    chart_mode = st.radio("Chart (for SQL results)", ["Auto", "Bar", "Line", "None"], horizontal=True, key="cchart")
    if "chist" not in st.session_state: st.session_state.chist = []
    if st.button("Ask", type="primary", key="cask") and q.strip():
        q, t0, item = q.strip(), time.time(), {"question": q.strip(), "sql": None, "docs": None}
        with st.spinner("Choosing where to look…"): item["route"] = rag.route(q, backend, model)
        if item["route"] in ("SQL", "BOTH"):
            with st.spinner("Querying the lakehouse…"):
                try: item["sql"] = t2s.ask(q, new_con(), backend, model, system=sysmsg)
                except Exception as e: item["sql"] = {"error": f"{type(e).__name__}: {e}", "sql": None}
        if item["route"] in ("TEXT", "BOTH"):
            item["docs"] = _docs_query(new_con, q, 6, backend, model)
        item["sec"] = round(time.time() - t0, 1)
        st.session_state.chist.insert(0, item)
    for n, it in enumerate(st.session_state.chist[:4]):
        with st.container(border=True):
            st.markdown(f"**{it['question']}**  · route: `{it['route']}` · {it['sec']}s")
            if it["sql"]:
                r = it["sql"]
                if r.get("error"): (st.info if r["error"].startswith("declined") else st.error)(r["error"])
                if r.get("sql"): st.code(r["sql"], language="sql")
                if not r.get("error"):
                    df = pd.DataFrame(r["rows"], columns=r["cols"])
                    st.dataframe(df, width="stretch", hide_index=True)
                    if n == 0: show_chart(df, chart_mode)
                    st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8-sig"), f"result_{n}.csv", key=f"cdl{n}")
            if it["docs"]: _docs_show(it["docs"], qual, backend, title=False)
