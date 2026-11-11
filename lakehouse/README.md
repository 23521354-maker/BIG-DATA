# VN30 annual reports on a Lakehouse (MinIO + Spark + Iceberg + Trino + Airflow)

Big-data version of the VN30 financial-indicator pipeline (MSIS406 final project). Runs on Docker Desktop
Kubernetes (kind, 3 nodes). The infrastructure manifests come from the Lakehouse project (`k8s/`); everything
specific to VN30 is in `spark/vn30_*.py`, `airflow/dags/vn30_pipeline.py` and `scripts/data/`.

## Architecture

```text
PDF + extractor output (MinIO bucket raw/vn30/)
   |  Spark  vn30_bronze.py   faithful copy of the sources
   v
Bronze  (Iceberg, bucket bronze)  vn30_bronze.pages_raw (17,952 pages) | extracted_raw (1,277) | cafef_raw (965)
   |  Spark  vn30_silver.py   CafeF cross-check per ticker, derived ROE/ROA, text chunks, dimensions
   v
Silver  (Iceberg, bucket silver)  vn30_silver.financial_indicators (1,674) | text_chunks (68,106) | companies (32) | metric_catalog (14)
   |  Spark SQL  vn30_gold.py
   v
Gold    (Iceberg, bucket gold)    vn30_gold.company_year_metrics (191) | data_quality_by_ticker (32)
   |  Trino (catalog iceberg)
   v
Text-to-SQL (Streamlit, engine "Trino") | dashboard
```

Airflow DAG `vn30_pipeline`: `vn30_bronze >> vn30_silver >> vn30_gold >> vn30_check >> verify_with_trino`.
`vn30_check` fails the run if any row count differs from the expected baseline.

## Run order (PowerShell, in this folder)

```powershell
.\scripts\setup\deploy.ps1            # first time only: MinIO, MySQL, Iceberg REST, Spark, Trino
.\scripts\setup\deploy-airflow.ps1    # first time only (use -SkipImage when the image is already loaded)
.\scripts\ops\mode-full.ps1           # start every service
.\scripts\data\upload-vn30.ps1        # sources -> MinIO raw/vn30/   (-SkipPdf for a quick first test)
.\scripts\dev\sync-airflow.ps1        # Spark jobs + DAG -> ConfigMaps (run again after editing a job)
# then either:
.\scripts\data\run-vn30.ps1           # all four Spark jobs by hand, or
#   Airflow UI (scripts\ops\port-forward.ps1 airflow -> http://localhost:8082, admin/admin) -> vn30_pipeline -> Trigger
.\scripts\ops\trino-query.ps1 "SELECT ticker, fiscal_year, net_profit_after_tax_bn FROM iceberg.vn30_gold.company_year_metrics WHERE ticker = 'VCB' ORDER BY fiscal_year"
```

Text-to-SQL on Trino: `pip install trino`, run `.\scripts\ops\port-forward.ps1 trino` in a second window, then
`python text2sql\eval_t2s.py --backend openai --model deepseek-flash --set golden.json`
or start the Streamlit UI (`text2sql\app.py`). Expected answers are frozen in `golden*.json` (field `gold`).

## Tests (no cluster needed)

The jobs also run locally when `VN30_LOCAL_OUT` is set (plain parquet instead of Iceberg):

```bash
export VN30_SRC=file:///path/to/BIG_DATA VN30_LOCAL_OUT=/tmp/vn30out
python spark/vn30_bronze.py && python spark/vn30_silver.py && python spark/vn30_gold.py && python spark/vn30_check.py
```

or in one step: `bash tests/run_local_test.sh /path/to/BIG_DATA`. Expected last line: `CHECK PASSED`.
