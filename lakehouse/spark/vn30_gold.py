"""Silver -> Gold for the VN30 annual-report (BCTN) project (Spark SQL).

Writes namespace `vn30_gold` (Iceberg, bucket `gold`):

  company_year_metrics    one row per (ticker, fiscal_year): the 14 metrics as columns (amounts in VND bn),
                          YoY growth of revenue and profit, and data-quality counters
  data_quality_by_ticker  one row per ticker: how many cells exist, how many need review, how many were
                          verified or filled by CafeF, how many were derived (ROE/ROA)

Set VN30_LOCAL_OUT to read/write plain parquet instead of Iceberg (local tests without a cluster).
"""
import os

from pyspark.sql import SparkSession

LOCAL_OUT = os.environ.get("VN30_LOCAL_OUT")

builder = SparkSession.builder.appName("VN30-Silver-To-Gold")
if LOCAL_OUT:
    builder = builder.master("local[2]")
spark = builder.getOrCreate()
spark.sparkContext.setLogLevel("WARN")
print("===== SPARK STARTED (VN30 gold) =====")


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


read_table("vn30_silver", "financial_indicators").createOrReplaceTempView("fi")
read_table("vn30_silver", "companies").createOrReplaceTempView("co")

# metric -> (output column, source column): amounts come in VND bn (value_bn_vnd), everything else keeps `value`
PIVOT = [
    ("net_revenue", "net_revenue_bn", "value_bn_vnd"), ("net_profit_after_tax", "net_profit_after_tax_bn", "value_bn_vnd"),
    ("total_assets", "total_assets_bn", "value_bn_vnd"), ("equity", "equity_bn", "value_bn_vnd"),
    ("net_interest_income", "net_interest_income_bn", "value_bn_vnd"),
    ("customer_loans", "customer_loans_bn", "value_bn_vnd"), ("customer_deposits", "customer_deposits_bn", "value_bn_vnd"),
    ("eps", "eps_vnd", "value"), ("roe", "roe_pct", "value"), ("roa", "roa_pct", "value"),
    ("employees", "employees", "value"), ("dividend", "dividend_pct", "value"),
    ("npl_ratio", "npl_ratio_pct", "value"), ("car", "car_pct", "value"),
]
cells = ",\n    ".join(f"MAX(CASE WHEN f.metric = '{m}' THEN f.{src} END) AS {col}" for m, col, src in PIVOT)

wide = spark.sql(f"""
SELECT
    f.ticker, f.fiscal_year, c.company_name, c.sector, c.is_bank,
    {cells},
    COUNT(*) AS n_metrics,
    SUM(CASE WHEN f.needs_review THEN 1 ELSE 0 END) AS n_needs_review,
    MAX(CASE WHEN f.method = 'cafef_verified' THEN true ELSE false END) AS has_cafef_value
FROM fi f
LEFT JOIN co c ON c.ticker = f.ticker
GROUP BY f.ticker, f.fiscal_year, c.company_name, c.sector, c.is_bank
""")
wide.createOrReplaceTempView("wide")

gold = spark.sql("""
SELECT
    w.*,
    CASE WHEN p.net_revenue_bn > 0
         THEN ROUND((w.net_revenue_bn / p.net_revenue_bn - 1) * 100, 2) END AS net_revenue_growth_pct,
    CASE WHEN p.net_profit_after_tax_bn > 0
         THEN ROUND((w.net_profit_after_tax_bn / p.net_profit_after_tax_bn - 1) * 100, 2) END AS net_profit_growth_pct
FROM wide w
LEFT JOIN wide p ON p.ticker = w.ticker AND p.fiscal_year = w.fiscal_year - 1
""")
write_table(gold, "vn30_gold", "company_year_metrics", "gold")

dq = spark.sql("""
SELECT
    f.ticker, c.sector, c.is_bank,
    COUNT(*) AS n_cells,
    COUNT(DISTINCT f.fiscal_year) AS n_years,
    SUM(CASE WHEN f.needs_review THEN 1 ELSE 0 END) AS n_needs_review,
    ROUND(SUM(CASE WHEN f.needs_review THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS needs_review_pct,
    SUM(CASE WHEN f.method = 'cafef_verified' THEN 1 ELSE 0 END) AS n_cafef_verified,
    SUM(CASE WHEN f.cafef_status = 'match' THEN 1 ELSE 0 END) AS n_cafef_match,
    SUM(CASE WHEN f.method LIKE 'derived%' THEN 1 ELSE 0 END) AS n_derived
FROM fi f LEFT JOIN co c ON c.ticker = f.ticker
GROUP BY f.ticker, c.sector, c.is_bank
""")
write_table(dq, "vn30_gold", "data_quality_by_ticker", "gold")

print("===== GOLD WRITTEN: company_year_metrics=%d data_quality_by_ticker=%d =====" % (
    read_table("vn30_gold", "company_year_metrics").count(), read_table("vn30_gold", "data_quality_by_ticker").count()))
spark.stop()
