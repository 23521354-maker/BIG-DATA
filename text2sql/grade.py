"""Result comparison used by eval_t2s.py, app.py and regrade.py (row order ignored; numbers equal within rounding tolerance)."""
from decimal import Decimal
TOL = 0.0051   # 2-decimal rounding can differ by 0.005 between engines (e.g. DuckDB ROUND vs Python round)
def _num(v): return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool)
def eq(a, b):
    if a is None or b is None: return a is None and b is None
    if _num(a) and _num(b): return abs(float(a) - float(b)) <= TOL
    return str(a) == str(b)
def _row_strict(p, g): return len(p) == len(g) and all(eq(x, y) for x, y in zip(p, g))
def _row_lenient(p, g):                      # every gold cell found in a distinct predicted cell (extra columns allowed)
    free = list(p)
    for y in g:
        for k, x in enumerate(free):
            if eq(x, y): free.pop(k); break
        else: return False
    return True
def _match(pred, gold, rowfn):
    if len(pred) != len(gold): return False
    free = list(pred)
    for g in gold:
        for k, p in enumerate(free):
            if rowfn(p, g): free.pop(k); break
        else: return False
    return True
def strict(pred, gold): return _match(pred, gold, _row_strict)
def lenient(pred, gold): return _match(pred, gold, _row_lenient)
