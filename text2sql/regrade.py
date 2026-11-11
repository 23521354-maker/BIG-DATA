"""Re-grade a saved eval json offline (no API calls): python regrade.py eval_golden_heldout_openai_deepseek-flash.json"""
import json, sys, os
from decimal import Decimal
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import t2s, grade
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
con = t2s.connect(); R = json.load(open(sys.argv[1], encoding="utf-8")); S = L = 0
for x in R:
    if x["kind"] == "unanswerable": S += x["ok"]; L += x["ok"]; continue
    if x["error"]: continue
    p = con.execute(x["sql"]).fetchall(); g = con.execute(x["gold_sql"]).fetchall()
    s = grade.strict(p, g); l = s or grade.lenient(p, g); S += s; L += l
    if not l: print(" still FAIL", x["id"], x["q"][:50], "| pred rows", len(p), "gold rows", len(g))
print(f"re-graded: strict {S}/{len(R)} | lenient {L}/{len(R)}")
