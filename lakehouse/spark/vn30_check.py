"""Data-quality gate for the VN30 pipeline: row counts of every Bronze/Silver/Gold table must equal the counts
of the single-machine baseline (Delta Lake build, verified cell by cell by tests/parity_silver.py), plus one
spot-check value. Exits with code 1 on any mismatch, so the Airflow task (and the DAG run) fails.
Set VN30_LOCAL_OUT to read parquet instead of Iceberg (local tests without a cluster)."""
import os
import sys

from pyspark.sql import SparkSession

LOCAL_OUT = os.environ.get("VN30_LOCAL_OUT")
builder = SparkSession.builder.appName("VN30-Check")
if LOCAL_OUT:
    builder = builder.master("local[2]")
spark = builder.getOrCreate()
spark.sparkContext.setLogLevel("WARN")

EXPECTED = {
    ("vn30_bronze", "pages_raw"): 17952,
    ("vn30_bronze", "extracted_raw"): 1277,
    ("vn30_bronze", "cafef_raw"): 965,
    ("vn30_silver", "financial_indicators"): 1674,
    ("vn30_silver", "text_chunks"): 68106,
    ("vn30_silver", "companies"): 32,
    ("vn30_silver", "metric_catalog"): 14,
    ("vn30_gold", "company_year_metrics"): 191,
    ("vn30_gold", "data_quality_by_ticker"): 32,
}


def read_table(ns, name):
    if LOCAL_OUT:
        return spark.read.parquet(os.path.join(LOCAL_OUT, ns, name))
    return spark.table(f"lakehouse.{ns}.{name}")


bad = 0
for (ns, name), want in EXPECTED.items():
    got = read_table(ns, name).count()
    flag = "OK" if got == want else "MISMATCH"
    bad += got != want
    print(f"{flag:9s} {ns}.{name}: {got} rows (expected {want})")

row = (read_table("vn30_silver", "financial_indicators")
       .filter("ticker = 'VCB' AND fiscal_year = 2023 AND metric = 'net_profit_after_tax'")
       .select("value_bn_vnd").collect())
val = row[0][0] if row else None
ok = val is not None and abs(val - 33054.448) < 1e-6
print(f"{'OK' if ok else 'MISMATCH':9s} spot check VCB 2023 net profit after tax = {val} bn VND (expected 33054.448)")
bad += not ok

spark.stop()
if bad:
    print(f"===== CHECK FAILED ({bad} problems) =====")
    sys.exit(1)
print("===== CHECK PASSED: lakehouse tables match the baseline =====")
