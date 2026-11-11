from decimal import Decimal
"""Execution-accuracy benchmark for t2s.py:  python eval_t2s.py --backend rules|ollama|openai|oracle [--model M]"""
import json, os, sys, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t2s, grade
def norm(rows):
    def c(v): return round(float(v), 2) if isinstance(v, (float, Decimal)) else v
    return sorted(tuple(str(c(v)) for v in r) for r in rows)
def lenient(pred, gold):
    """every gold row's cells appear inside a distinct predicted row (extra columns allowed), same row count"""
    if len(pred) != len(gold): return False
    P = [set(r) for r in norm(pred)]; used = set()
    for g in norm(gold):
        for k, p in enumerate(P):
            if k not in used and set(g) <= p: used.add(k); break
        else: return False
    return True
ap = argparse.ArgumentParser(); ap.add_argument("--backend", default="rules"); ap.add_argument("--model", default="qwen2.5-coder:7b"); ap.add_argument("--set", default="golden.json"); ap.add_argument("--engine", default="duckdb", choices=["duckdb", "trino"]); a = ap.parse_args()
ref = t2s.connect("duckdb"); con = t2s.connect(a.engine); G = json.load(open(os.path.join(t2s.HERE, a.set), encoding="utf-8")); res = []; sysmsg = None if a.backend in ("rules", "oracle") else t2s.system_prompt(con)
for g in G:
    if g["sql"] is None:   # unanswerable / unsafe: pass if the system declines, is blocked, or returns nothing
        r = t2s.ask(g["q"], con, a.backend, a.model, system=sysmsg) if a.backend != "oracle" else {"error": "declined: oracle", "rows": [], "sql": None, "attempts": 1}
        ok = (r["error"] is not None and ("declined" in r["error"] or "only SELECT" in r["error"] or "forbidden" in r["error"])) or (r["error"] is None and len(r["rows"]) == 0)
        res.append(dict(id=g["id"], q=g["q"], ok=ok, lenient_ok=ok, executed=r["error"] is None, error=r["error"], sql=r["sql"], gold_rows=0, pred_rows=len(r["rows"]), attempts=r["attempts"], kind="unanswerable")); continue
    gold = ref.execute(g["sql"]).fetchall()
    if a.backend == "oracle": r = {"sql": g["sql"], "rows": gold, "error": None, "attempts": 1}
    else: r = t2s.ask(g["q"], con, a.backend, a.model, system=sysmsg)
    ok = r["error"] is None and grade.strict(r["rows"], gold); lk = r["error"] is None and (ok or grade.lenient(r["rows"], gold))
    res.append(dict(id=g["id"], q=g["q"], ok=ok, lenient_ok=lk, executed=r["error"] is None, error=r["error"], sql=r["sql"], gold_rows=len(gold), pred_rows=len(r["rows"]), attempts=r["attempts"]))
n = len(res); print(f"backend={a.backend} strict {sum(x['ok'] for x in res)}/{n} | lenient(extra columns allowed) {sum(x['lenient_ok'] for x in res)}/{n} | executable {sum(x['executed'] for x in res)}/{n} | gold non-empty {sum(x['gold_rows']>0 for x in res)}/{n} (unanswerable items count as non-empty gold only if answered)")
for x in res:
    if not x["lenient_ok"]: print(" FAIL", x["id"], x["q"][:60], "|", (x["error"] or "wrong result")[:70])
json.dump(res, open(os.path.join(t2s.HERE, f"eval_{os.path.splitext(a.set)[0]}_{a.backend}_{a.model.replace(':','-').replace('/','-')}{'_trino' if a.engine == 'trino' else ''}.json" if a.backend not in ("rules","oracle") else f"eval_{a.backend}.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
