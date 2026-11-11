"""Load VN30 annual-report tables into Delta Lake (delta-rs). Tables: financial_indicators, text_chunks, companies, metric_catalog."""
import os, re, json, glob, csv, datetime as dt
import pyarrow as pa
from deltalake import write_deltalake, DeltaTable
BASE = os.path.dirname(os.path.abspath(__file__)); EX = os.path.join(BASE, "extract"); DL = os.environ.get("DELTA_OUT", os.path.join(BASE, "delta"))
NOW = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
def f(x):
    try: return float(x)
    except Exception: return None
def b(x): return str(x).strip().lower() == "true"
def i(x):
    try: return int(float(x))
    except Exception: return None
def s(x): return None if x in ("", None) else str(x)

# ---- financial_indicators
rows = list(csv.DictReader(open(os.path.join(EX, "financial_indicators_final_cafef.csv"), encoding="utf-8-sig")))
AMT = {"net_revenue","net_profit_after_tax","total_assets","equity","net_interest_income","customer_loans","customer_deposits"}
fi = []
for r in rows:
    vnd = f(r["value_vnd"]); src = r.get("source") or ("derived" if r["method"].startswith("derived") else "bctn")
    fi.append(dict(ticker=r["ticker"], fiscal_year=i(r["fiscal_year"]), metric=r["metric"], value=f(r["value"]), unit=s(r["unit"]),
        value_bn_vnd=(vnd / 1e9 if vnd is not None and r["metric"] in AMT else None), value_vnd=vnd, scope=s(r["scope"]),
        source_page=i(r["source_page"]), method=r["method"], source=src, confidence=f(r["confidence"]), needs_review=b(r["needs_review"]),
        value_prior=f(r["value_prior"]), cross_year_ok=b(r.get("cross_year_ok")), swapped=b(r.get("swapped")), conflict=b(r.get("conflict")),
        value_extracted=f(r.get("value_extracted")), cafef_value=f(r.get("cafef_value")), cafef_status=s(r.get("cafef_status")),
        cafef_url=s(r.get("cafef_url")), yoy_flag=s(r.get("yoy_flag")), raw_row=s(r.get("raw_row")), ingested_at=NOW))
sch_fi = pa.schema([("ticker", pa.string()), ("fiscal_year", pa.int32()), ("metric", pa.string()), ("value", pa.float64()), ("unit", pa.string()),
    ("value_bn_vnd", pa.float64()), ("value_vnd", pa.float64()), ("scope", pa.string()), ("source_page", pa.int32()), ("method", pa.string()),
    ("source", pa.string()), ("confidence", pa.float64()), ("needs_review", pa.bool_()), ("value_prior", pa.float64()), ("cross_year_ok", pa.bool_()),
    ("swapped", pa.bool_()), ("conflict", pa.bool_()), ("value_extracted", pa.float64()), ("cafef_value", pa.float64()), ("cafef_status", pa.string()),
    ("cafef_url", pa.string()), ("yoy_flag", pa.string()), ("raw_row", pa.string()), ("ingested_at", pa.timestamp("us"))])
t_fi = pa.Table.from_pylist(fi, schema=sch_fi)

# ---- text_chunks (page-based; long pages split by rows, ~1000 chars, 1-row overlap)
def split_rows(rs, cap=1000):
    out, cur, n = [], [], 0
    for r in rs:
        if cur and n + len(r) > cap:
            out.append(cur); cur = cur[-1:]; n = sum(len(x) for x in cur)
        cur.append(r); n += len(r) + 1
    if cur: out.append(cur)
    return out
ch = []
for fn in sorted(glob.glob(os.path.join(EX, "text", "*.json"))):
    name = os.path.basename(fn)[:-5]; m = re.match(r"([A-Z0-9]+)_(\d\d)CN", name)
    if not m: continue
    tk, fy = m.group(1), 2000 + int(m.group(2))
    for pg in json.load(open(fn, encoding="utf-8")):
        rs = [x.strip() for x in pg["rows"] if x and x.strip()]
        if sum(len(x) for x in rs) < 50: continue
        for k, part in enumerate(split_rows(rs)):
            txt = "\n".join(part)
            ch.append(dict(chunk_id=f"{tk}_{fy}_p{pg['p']:04d}_c{k:02d}", ticker=tk, fiscal_year=fy, source_file=name, page=int(pg["p"]), chunk_index=k,
                           text_source=pg["src"], n_chars=len(txt), text=txt, ingested_at=NOW))
sch_ch = pa.schema([("chunk_id", pa.string()), ("ticker", pa.string()), ("fiscal_year", pa.int32()), ("source_file", pa.string()), ("page", pa.int32()),
    ("chunk_index", pa.int32()), ("text_source", pa.string()), ("n_chars", pa.int32()), ("text", pa.string()), ("ingested_at", pa.timestamp("us"))])
t_ch = pa.Table.from_pylist(ch, schema=sch_ch)

# ---- companies (dimension; sector assigned manually) and metric_catalog (data dictionary)
CO = [("ACB","Asia Commercial Bank","Banking",1),("BCM","Becamex IDC","Real estate",0),("BID","BIDV","Banking",1),("BVH","Bao Viet Holdings","Insurance",0),
("CTG","VietinBank","Banking",1),("DGC","Duc Giang Chemicals","Materials",0),("FPT","FPT Corporation","Technology",0),("GAS","PV GAS","Energy & Utilities",0),
("GVR","Vietnam Rubber Group","Materials",0),("HDB","HDBank","Banking",1),("HPG","Hoa Phat Group","Materials",0),("LPB","LPBank","Banking",1),
("MBB","MB Bank","Banking",1),("MSN","Masan Group","Consumer",0),("MWG","Mobile World Group","Retail",0),("PLX","Petrolimex","Energy & Utilities",0),
("POW","PV Power","Energy & Utilities",0),("SAB","Sabeco","Consumer",0),("SHB","SHB","Banking",1),("SSB","SeABank","Banking",1),("SSI","SSI Securities","Securities",0),
("STB","Sacombank","Banking",1),("TCB","Techcombank","Banking",1),("TPB","TPBank","Banking",1),("VCB","Vietcombank","Banking",1),("VHM","Vinhomes","Real estate",0),
("VIB","VIB","Banking",1),("VIC","Vingroup","Real estate",0),("VJC","Vietjet Air","Aviation",0),("VNM","Vinamilk","Consumer",0),("VPB","VPBank","Banking",1),("VRE","Vincom Retail","Real estate",0)]
t_co = pa.Table.from_pylist([dict(ticker=a, company_name=b_, sector=c, is_bank=bool(d)) for a, b_, c, d in CO],
    schema=pa.schema([("ticker", pa.string()), ("company_name", pa.string()), ("sector", pa.string()), ("is_bank", pa.bool_())]))
MC = [("net_revenue","Net revenue","Doanh thu thuần","VND bn","amount","non-bank"),("net_profit_after_tax","Net profit after tax","Lợi nhuận sau thuế","VND bn","amount","all"),
("total_assets","Total assets","Tổng tài sản","VND bn","amount","all"),("equity","Owners' equity","Vốn chủ sở hữu","VND bn","amount","all"),
("net_interest_income","Net interest income","Thu nhập lãi thuần","VND bn","amount","bank"),("customer_loans","Customer loans","Cho vay khách hàng","VND bn","amount","bank"),
("customer_deposits","Customer deposits","Tiền gửi khách hàng","VND bn","amount","bank"),("eps","EPS","Lãi cơ bản trên cổ phiếu","VND","count","all"),
("roe","ROE","Tỷ suất sinh lời trên vốn chủ sở hữu","%","ratio","all"),("roa","ROA","Tỷ suất sinh lời trên tổng tài sản","%","ratio","all"),
("employees","Employees","Số lượng nhân viên","persons","count","all"),("dividend","Dividend","Cổ tức","%","ratio","all"),
("npl_ratio","NPL ratio","Tỷ lệ nợ xấu","%","ratio","bank"),("car","CAR","Hệ số an toàn vốn","%","ratio","bank")]
t_mc = pa.Table.from_pylist([dict(metric=a, name_en=b_, name_vi=c, unit=d, kind=e, applies_to=g) for a, b_, c, d, e, g in MC],
    schema=pa.schema([(k, pa.string()) for k in ("metric","name_en","name_vi","unit","kind","applies_to")]))

os.makedirs(DL, exist_ok=True)
for name, t in (("financial_indicators", t_fi), ("text_chunks", t_ch), ("companies", t_co), ("metric_catalog", t_mc)):
    write_deltalake(os.path.join(DL, name), t, mode="overwrite", schema_mode="overwrite")
    dtb = DeltaTable(os.path.join(DL, name)); print(name, "rows", t.num_rows, "version", dtb.version(), "files", len(dtb.file_uris()))
