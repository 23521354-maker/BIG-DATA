# Overlay CafeF annual figures (FY2020-2025) onto the extracted table. Keeps originals; labels provenance.
import os, csv
BASE = os.path.dirname(os.path.abspath(__file__)); EX = os.path.join(BASE, "extract")
MAP = {"npat": "net_profit_after_tax", "net_revenue": "net_revenue", "total_assets": "total_assets", "equity": "equity", "nii": "net_interest_income"}
RNG = {"net_revenue": (5e11, 6e14), "net_profit_after_tax": (2e11, 8e13), "total_assets": (5e12, 6e15), "equity": (3e12, 4e14), "net_interest_income": (1e12, 2e14)}
def num(s):
    s = s.strip()
    if s in ("", "NA", "N/A"): return None
    neg = s.startswith("-"); v = float(s.strip("()-").replace(",", "")); return -v if neg else v
rows = list(csv.DictReader(open(os.path.join(EX, "financial_indicators.csv"), encoding="utf-8-sig")))
cf = {}
UNIT = {"tỷ": 1.0, "triệu": 1e-3, "nghìn": 1e-6, "đồng": 1e-9}
def unit_scale(u):
    u = (u or "").lower()
    for k, f in UNIT.items():
        if k in u: return f
    return 1.0   # unknown -> assume billions (as in the 2022-2025 file)
for fn in ("cafef_bctc_nam_2022_2025.csv", "cafef_bctc_nam_2020_2021.csv"):
    p = os.path.join(EX, fn)
    if not os.path.exists(p): continue
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        v = num(r["value"])
        if v is not None and r["metric"] in MAP and 2020 <= int(r["year"]) <= 2025: cf[(r["ticker"], int(r["year"]), MAP[r["metric"]])] = (v * unit_scale(r.get("unit")), r["source_url"])
# sanity gate on CafeF values: plausible magnitude and equity < total assets
ok = {}
for k, (v, u) in cf.items():
    lo, hi = RNG[k[2]]
    if k[2] == "net_profit_after_tax": lo = 1e9   # CafeF values are explicit-unit; small profits (e.g. VJC 2021 = 79.66 bn) are legitimate
    if not (lo <= abs(v) * 1e9 <= hi): continue
    ta, eq = cf.get((k[0], k[1], "total_assets")), cf.get((k[0], k[1], "equity"))
    if k[2] in ("equity", "total_assets") and ta and eq and eq[0] >= ta[0]: continue
    ok[k] = (v, u)
print("CafeF keys", len(cf), "pass sanity", len(ok))
extra = ["source", "value_extracted", "cafef_value", "cafef_status", "cafef_url"]
out, seen, st = [], set(), {}
def bump(k): st[k] = st.get(k, 0) + 1
for r in rows:
    r = dict(r); k = (r["ticker"], int(r["fiscal_year"]), r["metric"]); r.update(source="bctn", value_extracted=r["value"], cafef_value="", cafef_status="", cafef_url="")
    if k in ok:
        v, u = ok[k]; seen.add(k); r["cafef_value"] = v; r["cafef_url"] = u
        try: mv = float(r["value_vnd"]) / 1e9
        except Exception: mv = None
        if mv is not None and abs(mv - v) <= 0.01 * abs(v):
            r["cafef_status"] = "match"; r["confidence"] = max(float(r["confidence"]), 0.95); r["needs_review"] = "False"; bump("match")
        else:
            hi = float(r["confidence"]) >= 0.8 and str(r["needs_review"]).lower() == "false"
            r.update(value=v, unit="ty dong", value_vnd=v * 1e9, method="cafef_verified", source="cafef", scope="unknown(cafef)", confidence=0.9, needs_review="False",
                     cafef_status="replaced_conflict" if hi else "replaced", swapped="", value_prior="", cross_year_ok="")
            bump(r["cafef_status"])
    out.append(r)
for k, (v, u) in ok.items():
    if k in seen: continue
    out.append(dict(ticker=k[0], fiscal_year=k[1], metric=k[2], value=v, unit="ty dong", value_vnd=v * 1e9, scope="unknown(cafef)", source_page="", method="cafef_verified",
                    confidence=0.9, needs_review="False", source="cafef", value_extracted="", cafef_value=v, cafef_status="added", cafef_url=u, raw_row=""))
    bump("added")
print(st)
# YoY plausibility flag (TA/equity should not change >2.5x or <0.4x between adjacent years)
V = {}
for r in out:
    try: V[(r["ticker"], int(r["fiscal_year"]), r["metric"])] = float(r["value_vnd"])
    except Exception: pass
nflag = 0
for r in out:
    r["yoy_flag"] = ""
    if r["metric"] not in ("total_assets", "equity"): continue
    k = (r["ticker"], int(r["fiscal_year"]), r["metric"]); v = V.get(k)
    for dy in (-1, 1):
        p = V.get((k[0], k[1] + dy, k[2]))
        if v and p and (v / p > 2.5 or v / p < 0.4):
            r["yoy_flag"] = "yoy_jump"; 
            if r.get("source") != "cafef": r["needs_review"] = "True"; r["confidence"] = min(float(r["confidence"]), 0.5)
            nflag += 1; break
print("yoy flagged", nflag, [(r["ticker"], r["fiscal_year"], r["metric"]) for r in out if r["yoy_flag"]])
cols = list(rows[0].keys()) + extra + ["yoy_flag"]
with open(os.path.join(EX, "financial_indicators_cafef.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(out)
print("rows", len(out))
