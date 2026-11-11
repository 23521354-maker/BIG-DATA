import csv, os, statistics, collections
EX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "extract")
rows = list(csv.DictReader(open(os.path.join(EX, os.environ.get("DR_IN","financial_indicators.csv")), encoding="utf-8-sig")))
cols = list(rows[0].keys())
R = {(r["ticker"], int(r["fiscal_year"]), r["metric"]): r for r in rows}
def f(x):
    try: return float(x)
    except: return None
def vnd(r):  # value in VND (None if unit unknown)
    return f(r["value_vnd"]) if r and r["value_vnd"] != "" else None
def prev_bal(t, y, m):
    """balance at end of year y-1: prefer the y-1 report's own value, else the prior column of report y."""
    r1 = R.get((t, y - 1, m))
    if r1 and vnd(r1) is not None: return vnd(r1), "prev_report"
    r = R.get((t, y, m))
    if r and r["value_prior"] != "" and r["unit"]:
        fac = f(r["value_vnd"]) / f(r["value"]) if f(r["value"]) else None
        if fac: return f(r["value_prior"]) * fac, "prior_col"
    return None, ""
BANKS = {"ACB","BID","CTG","HDB","MBB","SHB","SSB","STB","TCB","TPB","VCB","VIB","VPB","LPB","EIB","MSB"}
derived = {}
for (t, y, m), npat in list(R.items()):
    if m != "net_profit_after_tax": continue
    n = vnd(npat)
    if n is None: continue
    for out, base in (("roe", "equity"), ("roa", "total_assets")):
        b = R.get((t, y, base)); bv = vnd(b)
        if bv is None or bv <= 0: continue
        pv, how = prev_bal(t, y, base)
        denom, method = ((bv + pv) / 2, "derived") if pv and pv > 0 else (bv, "derived_end")
        val = n / denom * 100
        if abs(val) > (60 if out == "roe" else 35): continue
        conf = min(f(npat["confidence"]), f(b["confidence"]))
        conf = round(min(conf, 0.85 if method == "derived" else 0.7), 2)
        implausible = (t in BANKS and ((out == "roe" and not 5 <= val <= 40) or (out == "roa" and not 0.2 <= val <= 4))) or (t not in BANKS and out == "roe" and val < -30)
        if implausible: conf = min(conf, 0.6)
        derived[(t, y, out)] = dict(ticker=t, fiscal_year=y, metric=out, value=round(val, 2), unit="%", value_vnd="", scope=npat["scope"] or b["scope"],
            source_page=f'{npat["source_page"]}/{b["source_page"]}', method=method, confidence=conf, needs_review=conf < 0.8,
            value_prior="", cross_year_ok="", swapped="", raw_row=f'NPAT/{"avg(" if method=="derived" else ""}{base}{")" if method=="derived" else ""} x100')
# compare with reported
diffs = []
for k, d in derived.items():
    r = R.get(k)
    if r and f(r["value"]) is not None: diffs.append((k, f(r["value"]), d["value"]))
print("derived ROE/ROA records:", collections.Counter(k[2] for k in derived), "| methods:", collections.Counter(d["method"] for d in derived.values()))
if diffs:
    hi = [(k, a, b) for k, a, b in diffs if f(R[k]["confidence"]) >= 0.8]
    print("reported conf>=0.8 vs derived:", len(hi), "| within 3pp", f"{sum(abs(a-b)<=3 for _,a,b in hi)/max(len(hi),1):.0%}")
    ad = [abs(a - b) for _, a, b in diffs]
    print(f"overlap with reported: {len(diffs)} | median |diff| {statistics.median(ad):.2f} pp | within 1pp {sum(x<=1 for x in ad)/len(ad):.0%} | within 3pp {sum(x<=3 for x in ad)/len(ad):.0%} | >5pp {sum(x>5 for x in ad)}")
    print("largest gaps:", [(k[0], k[1], k[2], a, b) for k, a, b in sorted(diffs, key=lambda x: -abs(x[1] - x[2]))[:6]])
# final table: reported if it agrees (<=3pp) with derived; otherwise derived (reported kept in raw_row for audit); reported-only stays
final = [dict(r) for r in rows if (r["ticker"], int(r["fiscal_year"]), r["metric"]) not in derived]
agree = used_d = 0
for k, d in derived.items():
    r = R.get(k)
    if r and f(r["value"]) is not None and abs(f(r["value"]) - d["value"]) <= 3:
        r = dict(r); r["confidence"] = round(min(1.0, max(f(r["confidence"]), d["confidence"]) + 0.1), 2); r["needs_review"] = r["confidence"] < 0.8
        r["raw_row"] = f'reported agrees with derived {d["value"]}% | ' + r["raw_row"][:100]; final.append(r); agree += 1
    else:
        d = dict(d)
        if r and f(r["value"]) is not None: d["needs_review"] = True; d["raw_row"] += f' | conflicts with reported {r["value"]}% (p{r["source_page"]})'
        final.append(d); used_d += 1
final.sort(key=lambda r: (r["ticker"], int(r["fiscal_year"]), r["metric"]))
with open(os.path.join(EX, os.environ.get("DR_OUT","financial_indicators_final.csv")), "w", newline="", encoding="utf-8-sig") as fo:
    w = csv.DictWriter(fo, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(final)
cnt = collections.Counter(r["metric"] for r in final)
print(f"final records {len(final)} | ROE {cnt['roe']} ROA {cnt['roa']} (before: {sum(1 for r in rows if r['metric']=='roe')}/{sum(1 for r in rows if r['metric']=='roa')}) | reported agrees {agree} | derived used {used_d}")
import csv as _c
final_csv = list(_c.DictReader(open(os.path.join(EX, os.environ.get("DR_OUT","financial_indicators_final.csv")), encoding="utf-8-sig")))
final = final_csv
print("needs_review ROE/ROA:", sum(1 for r in final if r["metric"] in ("roe","roa") and r["needs_review"] == "True"), "| files with ROE:", len({(r["ticker"], r["fiscal_year"]) for r in final if r["metric"]=="roe"}), "| with ROA:", len({(r["ticker"], r["fiscal_year"]) for r in final if r["metric"]=="roa"}))
for t, y in (("VNM", 2024), ("VCB", 2023), ("MBB", 2024), ("DGC", 2023), ("FPT", 2023)):
    print(t, y, [(m, next((r["value"] for r in final if r["ticker"]==t and r["fiscal_year"]==str(y) and r["metric"]==m), None)) for m in ("roe", "roa")])
