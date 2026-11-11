"""Raw -> Bronze for the VN30 annual-report (BCTN) project.

Reads the files landed in s3a://raw/vn30/ (see scripts/upload-vn30.ps1) and writes three Iceberg tables
in namespace `vn30_bronze` (catalog `lakehouse`, bucket `bronze`). Nothing is cleaned here, Bronze is a
faithful copy of the source, one row per source record:

  pages_raw        one row per PDF page: extract/text/<TICKER>_<YY>CN_BCTN.json (text layer or OCR text)
  extracted_raw    extractor output before the CafeF cross-check: extract/financial_indicators.csv
  cafef_raw        CafeF annual figures (two CSVs: 2022-2025 and 2020-2021) with the source file name

Set VN30_LOCAL_OUT to write plain parquet instead of Iceberg (local tests without a cluster).
"""
import os

from pyspark.sql import SparkSession, functions as F, types as T

SRC = os.environ.get("VN30_SRC", "s3a://raw/vn30").rstrip("/")
LOCAL_OUT = os.environ.get("VN30_LOCAL_OUT")

builder = SparkSession.builder.appName("VN30-Raw-To-Bronze")
if LOCAL_OUT:
    builder = builder.master("local[2]")
spark = builder.getOrCreate()
spark.sparkContext.setLogLevel("WARN")
print("===== SPARK STARTED (VN30 bronze) =====")


def write_table(df, ns, name, bucket):
    if LOCAL_OUT:
        df.write.mode("overwrite").parquet(os.path.join(LOCAL_OUT, ns, name))
        return
    spark.sql(f"CREATE NAMESPACE IF NOT EXISTS lakehouse.{ns}")
    (df.writeTo(f"lakehouse.{ns}.{name}").using("iceberg")
       .tableProperty("location", f"s3://{bucket}/vn30/{name}")
       .tableProperty("format-version", "2").createOrReplace())


def read_csv(path):
    df = (spark.read.option("header", True).option("multiLine", True).option("quote", '"').option("escape", '"')
          .option("encoding", "UTF-8").csv(path))
    return df.toDF(*[c.lstrip("\ufeff") for c in df.columns])  # drop the BOM from the first column name


# ---- pages_raw: one JSON array of pages per PDF -> one row per page
page_schema = T.StructType([
    T.StructField("p", T.IntegerType()),
    T.StructField("src", T.StringType()),
    T.StructField("rows", T.ArrayType(T.StringType())),
])
pages = (spark.read.option("multiLine", True).schema(T.StructType([T.StructField("p", T.IntegerType()),
         T.StructField("src", T.StringType()), T.StructField("rows", T.ArrayType(T.StringType()))]))
         .json(f"{SRC}/extract/text/*.json")
         .withColumn("_path", F.input_file_name()))
pages = (pages
         .withColumn("source_file", F.regexp_extract("_path", r"([^/]+)\.json$", 1))
         .withColumn("ticker", F.regexp_extract("source_file", r"^([A-Z0-9]+)_\d\dCN", 1))
         .withColumn("yy", F.regexp_extract("source_file", r"^[A-Z0-9]+_(\d\d)CN", 1))
         .filter(F.col("ticker") != "")
         .withColumn("fiscal_year", (F.lit(2000) + F.col("yy").cast("int")).cast("int"))
         .select("source_file", "ticker", "fiscal_year", F.col("p").alias("page"),
                 F.col("src").alias("text_source"), F.col("rows"), F.current_timestamp().alias("_ingested_at")))
write_table(pages, "vn30_bronze", "pages_raw", "bronze")

# ---- extracted_raw: extractor output (all columns kept as strings, row order kept in _row_id)
ext = read_csv(f"{SRC}/extract/financial_indicators.csv").withColumn("_row_id", F.monotonically_increasing_id())
ext = ext.withColumn("_ingested_at", F.current_timestamp())
write_table(ext, "vn30_bronze", "extracted_raw", "bronze")

# ---- cafef_raw: both CafeF CSVs; _file_order keeps the 2022-2025 file before the 2020-2021 file
parts = []
for order, fn in enumerate(("cafef_bctc_nam_2022_2025.csv", "cafef_bctc_nam_2020_2021.csv")):
    d = (read_csv(f"{SRC}/extract/{fn}").withColumn("_source_file", F.lit(fn))
         .withColumn("_file_order", F.lit(order)).withColumn("_row_id", F.monotonically_increasing_id()))
    parts.append(d)
cf = parts[0].unionByName(parts[1]).withColumn("_ingested_at", F.current_timestamp())
write_table(cf, "vn30_bronze", "cafef_raw", "bronze")

def count(df):
    return df.count()

print("===== BRONZE WRITTEN: pages_raw=%d extracted_raw=%d cafef_raw=%d =====" % (count(pages), count(ext), count(cf)))
spark.stop()
