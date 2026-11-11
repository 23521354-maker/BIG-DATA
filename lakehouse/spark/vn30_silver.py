"""Bronze -> Silver for the VN30 annual-report (BCTN) project.

Reads namespace `vn30_bronze` and writes namespace `vn30_silver` (Iceberg, bucket `silver`):

  financial_indicators  one row per (ticker, fiscal_year, metric): extractor output + CafeF cross-check
                        (4 statuses: match / replaced / replaced_conflict / added), sanity gate, YoY flag,
                        derived ROE/ROA, full provenance columns (source, value_extracted, cafef_value,
                        cafef_status, cafef_url, yoy_flag)
  text_chunks           page text split into ~1000 character chunks with 1-row overlap
  companies             dimension: ticker, name, sector, is_bank
  metric_catalog        data dictionary of the 14 metrics

The cross-check (CafeF overlay), ratio derivation and typing logic is ported from an earlier single-machine
prototype and runs per ticker on the Spark cluster (RDD cogroup by ticker). Its output was verified cell by cell
against that prototype (0 differing cells) before the prototype was removed.
Set VN30_LOCAL_OUT to read/write plain parquet instead of Iceberg (local tests without a cluster).
"""
import os

from pyspark.sql import SparkSession, functions as F, types as T

LOCAL_OUT = os.environ.get("VN30_LOCAL_OUT")

builder = SparkSession.builder.appName("VN30-Bronze-To-Silver")
if LOCAL_OUT:
    builder = builder.master("local[2]")
spark = builder.getOrCreate()
spark.sparkContext.setLogLevel("WARN")
print("===== SPARK STARTED (VN30 silver) =====")


def read_table(ns, name):
    if LOCAL_OUT:
        return spark.read.parquet(os.path.join(LOCAL_OUT, ns, name))
    return spark.table(f"lakehouse.{ns}.{name}")


def write_table(df, ns, name, bucket):
    if LOCAL_OUT:
        df.write.mode("overwrite").parquet(os.path.join(LOCAL_OUT, ns, name))
        return
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS lakehouse.{ns}")
    (df.writeTo(f"lakehouse.{ns}.{name}").using("iceberg")
       .tableProperty("location", f"s3://{bucket}/vn30/{name}")
       .tableProperty("format-version", "2").createOrReplace())


# =====================================================================================
# Per-ticker logic (pure Python, runs on the executors)
# =====================================================================================
EXT_COLS = ["ticker", "fiscal_year", "metric", "value", "unit", "value_vnd", "scope", "source_page", "method",
            "confidence", "needs_review", "value_prior", "cross_year_ok", "swapped", "conflict", "unit_inferred",
            "oor", "hdr", "raw_row"]
EXTRA = ["source", "value_extracted", "cafef_value", "cafef_status", "cafef_url"]
ALL_COLS = EXT_COLS + EXTRA + ["yoy_flag"]

MAP = {"npat": "net_profit_after_tax", "net_revenue": "net_revenue", "total_assets": "total_assets",
       "equity": "equity", "nii": "net_interest_income"}
RNG = {"net_revenue": (5e11, 6e14), "net_profit_after_tax": (2e11, 8e13), "total_assets": (5e12, 6e15),
       "equity": (3e12, 4e14), "net_interest_income": (1e12, 2e14)}
UNIT = {"tỷ": 1.0, "triệu": 1e-3, "nghìn": 1e-6, "đồng": 1e-9}
BANKS = {"ACB", "BID", "CTG", "HDB", "MBB", "SHB", "SSB", "STB", "TCB", "TPB", "VCB", "VIB", "VPB", "LPB", "EIB", "MSB"}
AMT = {"net_revenue", "net_profit_after_tax", "total_assets", "equity", "net_interest_income", "customer_loans",
       "customer_deposits"}


def num(s):
    s = (s or "").strip()
    if s in ("", "NA", "N/A"):
        return None
    neg = s.startswith("-")
    v = float(s.strip("()-").replace(",", ""))
    return -v if neg else v


def unit_scale(u):
    u = (u or "").lower()
    for k, fac in UNIT.items():
        if k in u:
            return fac
    return 1.0  # unknown unit -> assume billions (as in the 2022-2025 file)


def ser(v):  # what csv.writer would write for this value
    return "" if v is None else str(v)


def f(x):
    try:
        return float(x)
    except Exception:
        return None


def to_float(x):
    return f(x)


def to_bool(x):
    return str(x).strip().lower() == "true"


def to_int(x):
    try:
        return int(float(x))
    except Exception:
        return None


def to_str(x):
    return None if x in ("", None) else str(x)


def apply_cafef(rows, cf_rows):
    """CafeF overlay for one ticker (ported from the earlier prototype). Returns list of dicts."""
    cf = {}
    for r in cf_rows:
        v = num(r.get("value"))
        if v is not None and r["metric"] in MAP and 2020 <= int(r["year"]) <= 2025:
            cf[(r["ticker"], int(r["year"]), MAP[r["metric"]])] = (v * unit_scale(r.get("unit")), r["source_url"])
    ok = {}
    for k, (v, u) in cf.items():  # sanity gate: plausible magnitude, equity < total assets
        lo, hi = RNG[k[2]]
        if k[2] == "net_profit_after_tax":
            lo = 1e9  # CafeF values carry an explicit unit; small profits (e.g. VJC 2021 = 79.66 bn) are legitimate
        if not (lo <= abs(v) * 1e9 <= hi):
            continue
        ta, eq = cf.get((k[0], k[1], "total_assets")), cf.get((k[0], k[1], "equity"))
        if k[2] in ("equity", "total_assets") and ta and eq and eq[0] >= ta[0]:
            continue
        ok[k] = (v, u)
    out, seen = [], set()
    for r in rows:
        r = dict(r)
        k = (r["ticker"], int(r["fiscal_year"]), r["metric"])
        r.update(source="bctn", value_extracted=r["value"], cafef_value="", cafef_status="", cafef_url="")
        if k in ok:
            v, u = ok[k]
            seen.add(k)
            r["cafef_value"] = v
            r["cafef_url"] = u
            try:
                mv = float(r["value_vnd"]) / 1e9
            except Exception:
                mv = None
            if mv is not None and abs(mv - v) <= 0.01 * abs(v):
                r["cafef_status"] = "match"
                r["confidence"] = max(float(r["confidence"]), 0.95)
                r["needs_review"] = "False"
            else:
                hi_conf = float(r["confidence"]) >= 0.8 and str(r["needs_review"]).lower() == "false"
                r.update(value=v, unit="ty dong", value_vnd=v * 1e9, method="cafef_verified", source="cafef",
                         scope="unknown(cafef)", confidence=0.9, needs_review="False",
                         cafef_status="replaced_conflict" if hi_conf else "replaced", swapped="", value_prior="",
                         cross_year_ok="")
        out.append(r)
    for k, (v, u) in ok.items():
        if k in seen:
            continue
        out.append(dict(ticker=k[0], fiscal_year=k[1], metric=k[2], value=v, unit="ty dong", value_vnd=v * 1e9,
                        scope="unknown(cafef)", source_page="", method="cafef_verified", confidence=0.9,
                        needs_review="False", source="cafef", value_extracted="", cafef_value=v,
                        cafef_status="added", cafef_url=u, raw_row=""))
    V = {}  # YoY plausibility flag: total assets / equity should not change >2.5x or <0.4x between adjacent years
    for r in out:
        try:
            V[(r["ticker"], int(r["fiscal_year"]), r["metric"])] = float(r["value_vnd"])
        except Exception:
            pass
    for r in out:
        r["yoy_flag"] = ""
        if r["metric"] not in ("total_assets", "equity"):
            continue
        k = (r["ticker"], int(r["fiscal_year"]), r["metric"])
        v = V.get(k)
        for dy in (-1, 1):
            p = V.get((k[0], k[1] + dy, k[2]))
            if v and p and (v / p > 2.5 or v / p < 0.4):
                r["yoy_flag"] = "yoy_jump"
                if r.get("source") != "cafef":
                    r["needs_review"] = "True"
                    r["confidence"] = min(float(r["confidence"]), 0.5)
                break
    # round-trip through strings exactly like the CSV hand-off between the two original scripts
    return [{c: ser(r.get(c)) for c in ALL_COLS} for r in out]


def derive_ratios(rows):
    """ROE/ROA from NPAT and average balances (ported from the earlier prototype). Returns list of dicts."""
    R = {(r["ticker"], int(r["fiscal_year"]), r["metric"]): r for r in rows}

    def vnd(r):
        return f(r["value_vnd"]) if r and r["value_vnd"] != "" else None

    def prev_bal(t, y, m):
        r1 = R.get((t, y - 1, m))
        if r1 and vnd(r1) is not None:
            return vnd(r1), "prev_report"
        r = R.get((t, y, m))
        if r and r["value_prior"] != "" and r["unit"]:
            fac = f(r["value_vnd"]) / f(r["value"]) if f(r["value"]) else None
            if fac:
                return f(r["value_prior"]) * fac, "prior_col"
        return None, ""

    derived = {}
    for (t, y, m), npat in list(R.items()):
        if m != "net_profit_after_tax":
            continue
        n = vnd(npat)
        if n is None:
            continue
        for out, base in (("roe", "equity"), ("roa", "total_assets")):
            b = R.get((t, y, base))
            bv = vnd(b)
            if bv is None or bv <= 0:
                continue
            pv, how = prev_bal(t, y, base)
            denom, method = ((bv + pv) / 2, "derived") if pv and pv > 0 else (bv, "derived_end")
            val = n / denom * 100
            if abs(val) > (60 if out == "roe" else 35):
                continue
            conf = min(f(npat["confidence"]), f(b["confidence"]))
            conf = round(min(conf, 0.85 if method == "derived" else 0.7), 2)
            implausible = (t in BANKS and ((out == "roe" and not 5 <= val <= 40) or (out == "roa" and not 0.2 <= val <= 4))) \
                or (t not in BANKS and out == "roe" and val < -30)
            if implausible:
                conf = min(conf, 0.6)
            derived[(t, y, out)] = dict(
                ticker=t, fiscal_year=y, metric=out, value=round(val, 2), unit="%", value_vnd="",
                scope=npat["scope"] or b["scope"], source_page=f'{npat["source_page"]}/{b["source_page"]}',
                method=method, confidence=conf, needs_review=conf < 0.8, value_prior="", cross_year_ok="", swapped="",
                raw_row=f'NPAT/{"avg(" if method == "derived" else ""}{base}{")" if method == "derived" else ""} x100')
    final = [dict(r) for r in rows if (r["ticker"], int(r["fiscal_year"]), r["metric"]) not in derived]
    for k, d in derived.items():
        r = R.get(k)
        if r and f(r["value"]) is not None and abs(f(r["value"]) - d["value"]) <= 3:
            r = dict(r)
            r["confidence"] = round(min(1.0, max(f(r["confidence"]), d["confidence"]) + 0.1), 2)
            r["needs_review"] = r["confidence"] < 0.8
            r["raw_row"] = f'reported agrees with derived {d["value"]}% | ' + r["raw_row"][:100]
            final.append(r)
        else:
            d = dict(d)
            if r and f(r["value"]) is not None:
                d["needs_review"] = True
                d["raw_row"] += f' | conflicts with reported {r["value"]}% (p{r["source_page"]})'
            final.append(d)
    final.sort(key=lambda r: (r["ticker"], int(r["fiscal_year"]), r["metric"]))
    return [{c: ser(r.get(c)) for c in ALL_COLS} for r in final]


def to_typed(r):
    """String row -> typed tuple, in the order of FI_SCHEMA (typing rules ported from the earlier prototype)."""
    vnd = to_float(r["value_vnd"])
    src = r.get("source") or ("derived" if r["method"].startswith("derived") else "bctn")
    return (r["ticker"], to_int(r["fiscal_year"]), r["metric"], to_float(r["value"]), to_str(r["unit"]),
            (vnd / 1e9 if vnd is not None and r["metric"] in AMT else None), vnd, to_str(r["scope"]),
            to_int(r["source_page"]), r["method"], src, to_float(r["confidence"]), to_bool(r["needs_review"]),
            to_float(r["value_prior"]), to_bool(r.get("cross_year_ok")), to_bool(r.get("swapped")),
            to_bool(r.get("conflict")), to_float(r.get("value_extracted")), to_float(r.get("cafef_value")),
            to_str(r.get("cafef_status")), to_str(r.get("cafef_url")), to_str(r.get("yoy_flag")),
            to_str(r.get("raw_row")))


def process_ticker(kv):
    _, (ext_it, cf_it) = kv
    ext = sorted(ext_it, key=lambda d: d["_row_id"])
    cf = sorted(cf_it, key=lambda d: (d["_file_order"], d["_row_id"]))
    ext = [{c: ("" if d.get(c) is None else d[c]) for c in EXT_COLS} for d in ext]
    cf = [{k: ("" if v is None else v) for k, v in d.items()} for d in cf]
    return [to_typed(r) for r in derive_ratios(apply_cafef(ext, cf))]


FI_SCHEMA = T.StructType([
    T.StructField("ticker", T.StringType()), T.StructField("fiscal_year", T.IntegerType()),
    T.StructField("metric", T.StringType()), T.StructField("value", T.DoubleType()),
    T.StructField("unit", T.StringType()), T.StructField("value_bn_vnd", T.DoubleType()),
    T.StructField("value_vnd", T.DoubleType()), T.StructField("scope", T.StringType()),
    T.StructField("source_page", T.IntegerType()), T.StructField("method", T.StringType()),
    T.StructField("source", T.StringType()), T.StructField("confidence", T.DoubleType()),
    T.StructField("needs_review", T.BooleanType()), T.StructField("value_prior", T.DoubleType()),
    T.StructField("cross_year_ok", T.BooleanType()), T.StructField("swapped", T.BooleanType()),
    T.StructField("conflict", T.BooleanType()), T.StructField("value_extracted", T.DoubleType()),
    T.StructField("cafef_value", T.DoubleType()), T.StructField("cafef_status", T.StringType()),
    T.StructField("cafef_url", T.StringType()), T.StructField("yoy_flag", T.StringType()),
    T.StructField("raw_row", T.StringType())])

# ---- financial_indicators
ext_kv = read_table("vn30_bronze", "extracted_raw").rdd.map(lambda r: (r["ticker"], r.asDict()))
cf_kv = read_table("vn30_bronze", "cafef_raw").rdd.map(lambda r: (r["ticker"], r.asDict()))
fi_rdd = ext_kv.cogroup(cf_kv).flatMap(process_ticker)
fi = spark.createDataFrame(fi_rdd, FI_SCHEMA).withColumn("ingested_at", F.current_timestamp())
write_table(fi, "vn30_silver", "financial_indicators", "silver")


# ---- text_chunks (page-based; long pages split by rows, ~1000 chars, 1-row overlap)
def split_rows(rs, cap=1000):
    out, cur, n = [], [], 0
    for r in rs:
        if cur and n + len(r) > cap:
            out.append(cur)
            cur = cur[-1:]
            n = sum(len(x) for x in cur)
        cur.append(r)
        n += len(r) + 1
    if cur:
        out.append(cur)
    return out


def chunk_page(rows):
    rs = [x.strip() for x in (rows or []) if x and x.strip()]
    if sum(len(x) for x in rs) < 50:
        return []
    return [(k, "\n".join(part)) for k, part in enumerate(split_rows(rs))]


chunk_udf = F.udf(chunk_page, T.ArrayType(T.StructType([T.StructField("k", T.IntegerType()),
                                                        T.StructField("txt", T.StringType())])))
tc = (read_table("vn30_bronze", "pages_raw")
      .withColumn("c", F.explode(chunk_udf("rows")))
      .select(
          F.format_string("%s_%d_p%04d_c%02d", "ticker", "fiscal_year", "page", F.col("c.k")).alias("chunk_id"),
          "ticker", "fiscal_year", "source_file", "page", F.col("c.k").alias("chunk_index"), "text_source",
          F.length(F.col("c.txt")).cast("int").alias("n_chars"), F.col("c.txt").alias("text"),
          F.current_timestamp().alias("ingested_at")))
write_table(tc, "vn30_silver", "text_chunks", "silver")

# ---- companies (dimension; sector assigned manually) and metric_catalog (data dictionary)
CO = [("ACB", "Asia Commercial Bank", "Banking", 1), ("BCM", "Becamex IDC", "Real estate", 0), ("BID", "BIDV", "Banking", 1),
      ("BVH", "Bao Viet Holdings", "Insurance", 0), ("CTG", "VietinBank", "Banking", 1),
      ("DGC", "Duc Giang Chemicals", "Materials", 0), ("FPT", "FPT Corporation", "Technology", 0),
      ("GAS", "PV GAS", "Energy & Utilities", 0), ("GVR", "Vietnam Rubber Group", "Materials", 0),
      ("HDB", "HDBank", "Banking", 1), ("HPG", "Hoa Phat Group", "Materials", 0), ("LPB", "LPBank", "Banking", 1),
      ("MBB", "MB Bank", "Banking", 1), ("MSN", "Masan Group", "Consumer", 0), ("MWG", "Mobile World Group", "Retail", 0),
      ("PLX", "Petrolimex", "Energy & Utilities", 0), ("POW", "PV Power", "Energy & Utilities", 0),
      ("SAB", "Sabeco", "Consumer", 0), ("SHB", "SHB", "Banking", 1), ("SSB", "SeABank", "Banking", 1),
      ("SSI", "SSI Securities", "Securities", 0), ("STB", "Sacombank", "Banking", 1), ("TCB", "Techcombank", "Banking", 1),
      ("TPB", "TPBank", "Banking", 1), ("VCB", "Vietcombank", "Banking", 1), ("VHM", "Vinhomes", "Real estate", 0),
      ("VIB", "VIB", "Banking", 1), ("VIC", "Vingroup", "Real estate", 0), ("VJC", "Vietjet Air", "Aviation", 0),
      ("VNM", "Vinamilk", "Consumer", 0), ("VPB", "VPBank", "Banking", 1), ("VRE", "Vincom Retail", "Real estate", 0)]
co = spark.createDataFrame([(a, b, c, bool(d)) for a, b, c, d in CO],
                           "ticker string, company_name string, sector string, is_bank boolean")
write_table(co, "vn30_silver", "companies", "silver")

MC = [("net_revenue", "Net revenue", "Doanh thu thuần", "VND bn", "amount", "non-bank"),
      ("net_profit_after_tax", "Net profit after tax", "Lợi nhuận sau thuế", "VND bn", "amount", "all"),
      ("total_assets", "Total assets", "Tổng tài sản", "VND bn", "amount", "all"),
      ("equity", "Owners' equity", "Vốn chủ sở hữu", "VND bn", "amount", "all"),
      ("net_interest_income", "Net interest income", "Thu nhập lãi thuần", "VND bn", "amount", "bank"),
      ("customer_loans", "Customer loans", "Cho vay khách hàng", "VND bn", "amount", "bank"),
      ("customer_deposits", "Customer deposits", "Tiền gửi khách hàng", "VND bn", "amount", "bank"),
      ("eps", "EPS", "Lãi cơ bản trên cổ phiếu", "VND", "count", "all"),
      ("roe", "ROE", "Tỷ suất sinh lời trên vốn chủ sở hữu", "%", "ratio", "all"),
      ("roa", "ROA", "Tỷ suất sinh lời trên tổng tài sản", "%", "ratio", "all"),
      ("employees", "Employees", "Số lượng nhân viên", "persons", "count", "all"),
      ("dividend", "Dividend", "Cổ tức", "%", "ratio", "all"),
      ("npl_ratio", "NPL ratio", "Tỷ lệ nợ xấu", "%", "ratio", "bank"),
      ("car", "CAR", "Hệ số an toàn vốn", "%", "ratio", "bank")]
mc = spark.createDataFrame(MC, "metric string, name_en string, name_vi string, unit string, kind string, applies_to string")
write_table(mc, "vn30_silver", "metric_catalog", "silver")

print("===== SILVER WRITTEN: financial_indicators=%d text_chunks=%d companies=%d metric_catalog=%d =====" % (
    read_table("vn30_silver", "financial_indicators").count(), read_table("vn30_silver", "text_chunks").count(),
    read_table("vn30_silver", "companies").count(), read_table("vn30_silver", "metric_catalog").count()))
spark.stop()
