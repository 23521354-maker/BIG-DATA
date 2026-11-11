import os, re, json, glob, csv, unicodedata, collections
BASE = os.path.dirname(os.path.abspath(__file__)); EX = os.path.join(BASE, "extract")
BANKS = {"ACB","BID","CTG","HDB","MBB","SHB","SSB","STB","TCB","TPB","VCB","VIB","VPB","LPB","EIB","MSB"}
def norm(s):
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()

# metric: (aliases, kind, applies_to, page_flag_bonus)
M = {
 "net_revenue":    (["doanh thu thuan"], "amount", "corp", ("IS","KPI")),
 "net_profit_after_tax": (["loi nhuan sau thue thu nhap doanh nghiep","loi nhuan sau thue tndn","loi nhuan sau thue"], "amount", "all", ("IS","KPI")),
 "total_assets":   (["tong cong tai san","tong tai san"], "amount", "all", ("BS","KPI")),
 "equity":         (["von chu so huu"], "amount", "all", ("BS","KPI")),
 "eps":            (["lai co ban tren co phieu","lai co ban","thu nhap tren moi co phieu","eps"], "count", "all", ("IS","KPI")),
 "roe":            (["ty suat sinh loi tren von chu so huu","ty suat loi nhuan tren von chu so huu","roe"], "ratio", "all", ("KPI",)),
 "roa":            (["ty suat sinh loi tren tong tai san","ty suat loi nhuan tren tong tai san","roa"], "ratio", "all", ("KPI",)),
 "employees":      (["so luong lao dong","tong so can bo nhan vien","tong so nhan vien","so luong nhan vien","tong so lao dong"], "count", "all", ()),
 "dividend":       (["co tuc"], "ratio", "all", ()),
 "net_interest_income": (["thu nhap lai thuan"], "amount", "bank", ("IS","KPI")),
 "customer_loans": (["cho vay khach hang"], "amount", "bank", ("BS","KPI")),
 "customer_deposits": (["tien gui cua khach hang","tien gui khach hang"], "amount", "bank", ("BS","KPI")),
 "npl_ratio":      (["ty le no xau","no xau"], "ratio", "bank", ("KPI",)),
 "car":            (["he so an toan von","car"], "ratio", "bank", ("KPI",)),
}
AMT = re.compile(r"(?<![\d.,])\(?-?\d{1,3}(?:[.,]\d{3})+\)?(?![\d])")
CNT = re.compile(r"(?<![\d.,])-?\d{1,3}(?:[.,]\d{3})*(?![\d.,%])")
RAT = re.compile(r"(?<![\d.,])-?\d{1,3}(?:[.,]\d{1,2})?(?:\s*%)")
RAT2 = re.compile(r"(?<![\d.,])-?\d{1,3}[.,]\d{1,2}(?![\d])")
def toi(s):
    neg = "(" in s or "-" in s
    v = int(re.sub(r"[^\d]", "", s)); return -v if neg else v
def tof(s):
    s = s.replace("%", "").strip(); neg = s.startswith("-"); s = s.lstrip("-").replace(",", ".")
    v = float(s); return -v if neg else v
def parse(rest, kind):
    if kind == "amount": return [toi(x) for x in AMT.findall(rest)]
    if kind == "ratio":
        vals = [tof(x) for x in RAT.findall(rest)] or [tof(x) for x in RAT2.findall(rest)]
        return [v for v in vals if abs(v) < 100]
    toks = CNT.findall(rest); vals = [toi(t) for t in toks]
    vals = [v for v in vals if not (2010 <= v <= 2030)]
    if any(abs(v) >= 1000 for v in vals): vals = [v for v in vals if abs(v) >= 1000]
    return vals
def page_flags(nrows):
    t = " ".join(nrows); f = set()
    if "can doi ke toan" in t or ("tong cong tai san" in t and "no phai tra" in t): f.add("BS")
    if "ket qua hoat dong" in t or ("doanh thu" in t and "loi nhuan sau thue" in t): f.add("IS")
    if "bao cao ket qua hoat dong" in t or "bao cao ket qua kinh doanh" in t: f.add("ISS")
    if "bang can doi ke toan" in t or "bao cao tinh hinh tai chinh" in t: f.add("BSS")
    if "chi tieu tai chinh" in t or "chi so tai chinh" in t or "tinh hinh tai chinh" in t: f.add("KPI")
    return f
def unit_of(nrows):
    t = " ".join(nrows)
    for pat, u, fac in ((r"ty dong|ty vnd", "ty dong", 1e9), (r"trieu dong|trieu vnd|million", "trieu dong", 1e6),
                        (r"nghin dong|ngan dong|nghin vnd", "nghin dong", 1e3), (r"don vi tinh:?\s*(vnd|dong)|\bvnd\b", "dong", 1)):
        if re.search(pat, t): return u, fac
    return "", None
def scope_of(nrows):
    t = " ".join(nrows); h = t.count("hop nhat"); r = t.count("rieng le") + t.count("cong ty me")
    return "hop nhat" if h >= max(1, r) else ("rieng le" if r > h else "")

OTHER = sorted({a for v in M.values() for a in v[0] if len(a) > 4} | {"he so","ty suat","ty le","chi so","loi nhuan","doanh thu","tong cong","tong tai san","von chu so","tong no"}, key=len, reverse=True)
def cut(rest, own):
    pos = len(rest)
    for o in OTHER:
        if o == own or own.startswith(o) and False: continue
        q = rest.find(o)
        if 0 <= q < pos and not own.startswith(o) and not o.startswith(own): pos = q
    return rest[:pos]
NEG = {"net_profit_after_tax": ["chua phan phoi","luy ke","tren co phieu","khong kiem soat","cong ty me","cua co dong","truoc thue","dau ky","cuoi nam","cuoi ky"],
       "net_revenue": ["trong nuoc","xuat khau","nuoc ngoai","bo phan","thi truong","tang truong","dat ","tang "],
       "equity": ["tong no phai tra va","no phai tra va von","tong nguon von","tong cong nguon von","loi nhuan tren von","ty suat sinh loi"]}
# v2: plausible magnitude (VND) of annual figures for VN30 issuers; used to catch wrong unit / wrong column
RNG = {"net_revenue": (5e11, 6e14), "net_profit_after_tax": (2e11, 8e13), "total_assets": (5e12, 6e15),
       "equity": (3e12, 4e14), "net_interest_income": (1e12, 2e14)}
def rng_ok(met, vnd):
    r = RNG.get(met); return True if r is None or vnd is None else r[0] <= abs(vnd) <= r[1]
def hdr_years(nr, i, n_needed):
    """nearest header row above row i that lists >=2 years; return years only when count matches number of columns"""
    for j in range(i - 1, max(-1, i - 60), -1):
        ys = list(dict.fromkeys(re.findall(r"(?<!\d)(20[12]\d)(?!\d)", nr[j])))
        if len(ys) >= 2: return [int(y) for y in ys] if len(ys) == n_needed else None
    return None
SUBNOTE = re.compile(r"\s*\d{1,2}\.\d{1,2}\.?\s")
def skel(x): return re.sub(r"[aeiouy]", "", x)
def skel_pos(x):
    out, pos = [], []
    for i, ch in enumerate(x):
        if ch not in "aeiouy": out.append(ch); pos.append(i)
    return "".join(out), pos
cands = []
for fn in sorted(glob.glob(os.path.join(EX, "text", "*.json"))):
    name = os.path.basename(fn)[:-5]; m = re.match(r"([A-Z0-9]+)_(\d\d)CN", name)
    ticker, fy = m.group(1), 2000 + int(m.group(2)); bank = ticker in BANKS
    for pg in json.load(open(fn, encoding="utf-8")):
        rows = pg["rows"]; nr = [norm(r) for r in rows]; fl = page_flags(nr)
        unit, fac = unit_of(nr); scope = scope_of(nr)
        for met, (aliases, kind, who, bonus) in M.items():
            if (who == "bank" and not bank) or (who == "corp" and bank): continue
            for i, n in enumerate(nr):
                for a in aliases:
                    k = n.find(a); smode = False
                    if k < 0 and pg["src"] == "ocr" and len(skel(a)) >= 6:
                        ns, pos = skel_pos(n); ask = skel(a); q = ns.find(ask)
                        if q >= 0: k = pos[q]; smode = True
                    if k >= 0 and any((skel(w) in skel(n)) if smode else (w in n) for w in NEG.get(met, [])): continue
                    if k < 0 or (len(a) <= 4 and not re.search(r"\b" + a + r"\b", n)): continue
                    rest = cut(n[k:] if smode else n[k + len(a):], a if not smode else ""); nums = parse(rest, kind); j = i; wrapped = False
                    if not nums and j + 1 < len(nr):
                        j += 1; wrapped = True; nums = parse(nr[j], kind)
                    while len(nums) < 2 and j < i + 3 and j + 1 < len(nr):
                        j += 1
                        if len(re.findall(r"[a-z]", nr[j])) > 6: break
                        nums += parse(nr[j], kind)
                    if not nums: continue
                    mono = all(nums[x] < nums[x + 1] for x in range(len(nums) - 1)) or all(nums[x] > nums[x + 1] for x in range(len(nums) - 1))
                    hdr = ""
                    if kind in ("amount", "ratio") and len(nums) >= 3:   # 2-column rows: orientation is decided by cross-year evidence (plan/actual tables fooled the header rule)
                        hy = hdr_years(nr, i, len(nums))
                        if hy and all(hy[x] < hy[x + 1] for x in range(len(hy) - 1)): nums = nums[::-1]; hdr = "asc_reversed"
                        elif hy and all(hy[x] > hy[x + 1] for x in range(len(hy) - 1)): hdr = "desc_ok"
                    if not hdr and kind in ("amount", "ratio") and len(nums) >= 4 and all(nums[x] < nums[x + 1] for x in range(len(nums) - 1)): nums = nums[::-1]
                    score = (-0.5 if wrapped else 0) - (3 if kind == "amount" and len(nums) >= 5 and not mono else 0) - (3 if kind == "amount" and SUBNOTE.match(n) else 0) - (1.5 if k >= 15 else 0) + (4 if ('IS' in bonus and 'ISS' in fl) or ('BS' in bonus and 'BSS' in fl) else 0) + sum(3 for b in bonus if b in fl) + (1 if len(nums) >= 2 else 0) + (3 if scope == "hop nhat" else (-3 if scope == "rieng le" else 0)) \
                            + (0.5 if pg["src"] == "text" else 0) + (1 if k < 6 else 0)
                    ufac, uname, inferred, oor = (fac if kind == "amount" else ""), (unit if kind == "amount" else ("%" if kind == "ratio" else "")), False, False
                    if kind == "amount" and met in RNG:
                        if ufac is not None and rng_ok(met, nums[0] * ufac): pass
                        elif ufac in (None, 1):   # unit missing or only 'VND' guessed: infer scale from plausible magnitude
                            for f2, u2 in ((1e6, "trieu dong"), (1e9, "ty dong"), (1e3, "nghin dong"), (1, "dong")):
                                if rng_ok(met, nums[0] * f2): ufac, uname, inferred = f2, u2, True; break
                            else: oor = True
                        else: oor = True          # unit detected but magnitude implausible -> penalise, do not reinterpret
                    if oor: score -= 5
                    cands.append(dict(ticker=ticker, fiscal_year=fy, metric=met, value=nums[0],
                                      value_prior=nums[1] if len(nums) > 1 else "", unit=uname,
                                      unit_factor=ufac if kind == "amount" else "", scope=scope, source_page=pg["p"],
                                      method="text_layer" if pg["src"] == "text" else "ocr_ppocrv6", score=score, raw_row=rows[i][:160],
                                      unit_inferred=inferred, oor=oor, hdr=hdr))
                    break
def close(a, b):
    return a != "" and b != "" and abs(a - b) <= max(1e-9, 0.005 * max(abs(a), abs(b)))
pc, pp = collections.defaultdict(list), collections.defaultdict(list)
for c in cands:
    if c["oor"]: continue
    k = (c["ticker"], c["metric"], c["fiscal_year"]); pc[k].append(c["value"]); pp[k].append(c["value_prior"])
def anyc(v, pool): return int(v != "" and any(close(v, x) for x in pool))
for c in cands:
    t, m, y = c["ticker"], c["metric"], c["fiscal_year"]
    cur_prev, pri_next = pc.get((t, m, y - 1), []), pp.get((t, m, y + 1), [])
    e1 = anyc(c["value_prior"], cur_prev) + anyc(c["value"], pri_next)
    e2 = anyc(c["value"], cur_prev) + anyc(c["value_prior"], pri_next)
    plaus = c["unit_factor"] in ("", None) or c["value_prior"] == "" or rng_ok(m, c["value_prior"] * c["unit_factor"])
    if e2 > e1 and c["value_prior"] != "" and plaus:
        c["value"], c["value_prior"] = c["value_prior"], c["value"]; c["swapped"] = True; c["ev"] = e2
    else: c["swapped"] = False; c["ev"] = e1
best = {}
for c in cands:
    key = (c["ticker"], c["fiscal_year"], c["metric"])
    rk = lambda z: (not z["oor"], z["ev"], z["score"])
    if key not in best or rk(c) > rk(best[key]): best[key] = c
bykey = collections.defaultdict(list)
for c in cands: bykey[(c["ticker"], c["fiscal_year"], c["metric"])].append(c)
def vv(c):
    try: return float(c["value"]) * float(c["unit_factor"]) if c["unit_factor"] not in ("", None) else (float(c["value"]) if c["metric"] in ("roe","roa","npl_ratio","car","dividend") else None)
    except: return None
def conflict(c):
    a = vv(c)
    if a is None or a == 0: return False
    for o in bykey[(c["ticker"], c["fiscal_year"], c["metric"])]:
        if o is c or o["score"] < max(6, c["score"] - 1) or o["source_page"] == c["source_page"]: continue
        b = vv(o)
        if b not in (None, 0) and abs(a - b) > 0.01 * max(abs(a), abs(b)): return True
    return False
out = []
for (t, y, met), c in sorted(best.items()):
    conf = min(1.0, 0.4 + 0.05 * min(c["score"], 6) + 0.15 * c["ev"])
    if met in ("dividend", "employees") and c["ev"] == 0: conf = min(conf, 0.5)
    cf = conflict(c)
    if cf: conf = min(conf, 0.6)
    if c["oor"]: conf = min(conf, 0.4)
    if c["unit_inferred"]: conf = min(conf, 0.7)
    c = dict(c); c["cross_year_ok"] = c["ev"] > 0; c["confidence"] = round(conf, 2); c["conflict"] = cf
    c["needs_review"] = (conf < 0.8) or c["value_prior"] == "" or cf or c["oor"] or c["unit_inferred"]
    c["value_vnd"] = c["value"] * c["unit_factor"] if c["unit_factor"] not in ("", None) else ""
    out.append(c)
cols = ["ticker","fiscal_year","metric","value","unit","value_vnd","scope","source_page","method","confidence","needs_review","value_prior","cross_year_ok","swapped","conflict","unit_inferred","oor","hdr","raw_row"]
with open(os.path.join(EX, "financial_indicators.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(out)
with open(os.path.join(EX, "candidates_all.csv"), "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=list(cands[0].keys())); w.writeheader(); w.writerows(cands)
print("candidates", len(cands), "| chosen records", len(out))
cov = collections.Counter(c["metric"] for c in out); print("coverage per metric (max ~154 files):", dict(cov))
print("cross-year OK:", sum(c["cross_year_ok"] for c in out), "| needs_review:", sum(c["needs_review"] for c in out))
