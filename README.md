# VN30 annual reports -> Lakehouse -> Text-to-SQL

MSIS406 final project (group DICTATOR, University of Information Technology, VNU-HCM).
Financial indicators of 32 VN30 companies, fiscal years 2020-2025, extracted from annual-report PDFs, cross-checked against a second source,
stored in a **lakehouse (MinIO + Spark + Iceberg + Trino + Airflow)** and queried in natural language (Vietnamese or English) through **Text-to-SQL on Trino**.

## Architecture

```text
PDF annual reports ──(offline extraction: text, OCR, rules)──> extract/ (text JSON + CSV)
                                                                  │  upload
                                                                  v
                                   MinIO  raw/vn30/                          (object storage)
                                                                  │  Spark  vn30_bronze.py
                                   Bronze  vn30_bronze.{pages_raw 17,952 | extracted_raw 1,277 | cafef_raw 965}
                                                                  │  Spark  vn30_silver.py   (cross-check, derived ROE/ROA, text chunks)
                                   Silver  vn30_silver.{financial_indicators 1,674 | text_chunks 68,106 | companies 32 | metric_catalog 14}
                                                                  │  Spark SQL  vn30_gold.py
                                   Gold    vn30_gold.{company_year_metrics 191 | data_quality_by_ticker 32}
                                                                  │  Iceberg REST catalog + Trino
                                   Text-to-SQL (Streamlit, LLM -> SQL -> Trino)
Orchestration: Airflow DAG vn30_pipeline = bronze >> silver >> gold >> check >> verify_with_trino
```

The extraction step (`PDF -> extract/`) is deliberately **offline**: it needs OCR, takes hours and its output is frozen after verification.
The lakehouse starts from `extract/`. See [DATA.md](DATA.md) for what each data pack contains.

## Repository map

| Path | What it is |
|---|---|
| `lakehouse/` | The big-data stack: Kubernetes manifests, Spark jobs (`spark/`), Airflow DAG (`airflow/`), PowerShell scripts, tests. Has its own [README](lakehouse/README.md) |
| `text2sql/` | Text-to-SQL engine (`t2s.py`), Streamlit UI (`app.py`), evaluation (`eval_t2s.py`), test sets (`golden*.json`) and stored results (`eval_*.json`) |
| `download_vn30.py`, `inventory_vn30.py`, `dump_text.py`, `locate_pages.py`, `scan_tess.py`, `ppocr_batch.py`, `extract_indicators.py` | Ingestion / extraction (offline, optional) |
| `apply_cafef.py`, `derive_ratios.py`, `load_delta.py` | Original single-machine pipeline (Delta Lake). Superseded by the Spark jobs but kept as the **reference** for the parity test and for gold answers in the evaluation |
| `selected_files.csv`, `missing_files.csv` | The 154 reports that were processed (with SHA-256) and the 38 ticker-years that do not exist at the source |
| `requirements.txt`, `requirements-ingestion.txt` | Python dependencies (the second one is only for reproducing the extraction) |

## Three ways to try it

You need the **core data pack** ([DATA.md](DATA.md)) unzipped in the repository root: `extract/` and `delta/`.

### 1. Local Spark test, no cluster (about 3 minutes)

Linux, macOS or WSL2 with Java 11 or 17.

```bash
pip install -r requirements.txt
bash lakehouse/tests/run_local_test.sh .      # bronze -> silver -> gold -> check -> parity with the Delta reference
```

Expected last lines: `CHECK PASSED: lakehouse tables match the baseline` and `PARITY OK` (0 differing cells in the 4 Silver tables).
This runs the same Spark code, writing plain parquet instead of Iceberg tables. It has not been tried on native Windows (Spark needs `winutils` there) - use WSL2.

### 2. Full lakehouse on Docker Desktop Kubernetes

Windows, Docker Desktop with Kubernetes (kind, 3 nodes) and PowerShell. Step by step in [lakehouse/README.md](lakehouse/README.md):
deploy the stack, upload `extract/` to MinIO, run the Airflow DAG `vn30_pipeline` (or `run-vn30.ps1`), then query Trino.
Reference run: all four Spark jobs and the Airflow DAG finish in a few minutes; Trino returns 1,674 Silver rows and 191 Gold rows;
VCB 2023 net profit after tax = 33,054.448 billion VND.

### 3. Text-to-SQL

```bash
pip install -r requirements.txt
cd text2sql
python eval_t2s.py --backend oracle --set golden.json                                   # no LLM: reference SQL, expect 31/31
export OPENAI_API_KEY=...                                                               # your own DeepSeek (or OpenAI-compatible) key
python eval_t2s.py --backend openai --model deepseek-flash --engine duckdb --set golden.json
python eval_t2s.py --backend openai --model deepseek-flash --engine trino  --set golden.json   # needs the lakehouse + port-forward to Trino
python -m streamlit run app.py                                                          # UI; type the key in the sidebar
```

On PowerShell set the key with `$env:OPENAI_API_KEY = "..."`. **Never commit a key.** The key is read from the environment or typed in the UI and is not stored anywhere.
Gold answers are always computed on the DuckDB reference over `delta/`, whichever engine is being tested.

## Results

Data (all checked in the Spark jobs by `vn30_check.py` against the single-machine baseline; Silver equals the Delta reference cell by cell).

Text-to-SQL, execution accuracy; *strict* = same rows and columns, *lenient* = extra columns allowed.

| Model / engine | Dev set (31 questions) strict / lenient | Held-out set (27 questions) strict / lenient |
|---|---|---|
| deepseek-flash, DuckDB | 18 / 31 | 16 / 26 |
| deepseek-flash, **Trino (lakehouse)** | 18 / 31, all 31 SQL executable | not run on Trino |
| deepseek-v4-pro, DuckDB | 21 / 30 | 17 / 25 |
| oracle (reference SQL) | 31 / 31 | - |

The held-out set contains 4 unanswerable questions, all declined correctly by deepseek-flash.

## Known limitations

* The test sets are small and written by the authors. The held-out set was looked at while improving the prompt, so it is **not** an independent test.
* BVH: total assets and equity for 2021-2024 are missing. BCM and BVH for 2020 could not be cross-checked. 448 Silver rows are flagged `needs_review`.
* 38 of the 192 ticker-years (32 companies x 6 years) have no PDF at the source. Of the 154 reports processed, 4 produced no text chunks (BID 2021, BVH 2023, STB 2021, STB 2022), so `text_chunks` covers 150 reports.
* Extraction is rule-based plus OCR; a few values were corrected by hand and are labelled with their source in `financial_indicators.source`.
* Spark executors are set to 512 MB (Docker Desktop on a laptop); raise it in `lakehouse/scripts/data/run-vn30.ps1` and `airflow/dags/vn30_pipeline.py` if you see out-of-memory errors.

## Security note

The Kubernetes manifests contain **lab-only** credentials (MinIO `admin/password123`, MySQL `root123` / `iceberg123`, Airflow `admin/admin` and a fixed Airflow web-server secret key) so the stack starts without setup.
Everything is local to your machine and not exposed; never reuse these values anywhere else. No real API key is in this repository.

## Data and licensing

* Annual-report PDFs come from *Vietnam Listed Companies Annual Reports PDF Dataset, 2000-2025* (Ngo Phu Thanh, 2026, v1.0.0),
  https://doi.org/10.5281/zenodo.20949551, CC BY 4.0. Please cite it if you reuse the data.
* The CafeF cross-check tables are third-party data and are not redistributed here.
* Code license: to be decided by the authors (see `LICENSE` once added).
