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
| `text2sql/` | Text-to-SQL engine (`t2s.py`), Streamlit UI (`app.py`), evaluation (`eval_t2s.py`), test sets with frozen expected answers (`golden*.json`) and stored results (`eval_*.json`) |
| `download_vn30.py`, `inventory_vn30.py`, `dump_text.py`, `locate_pages.py`, `scan_tess.py`, `ppocr_batch.py`, `extract_indicators.py` | Ingestion / extraction (offline, optional) |
| `selected_files.csv`, `missing_files.csv` | The 154 reports that were processed (with SHA-256) and the 38 ticker-years that do not exist at the source |
| `requirements.txt`, `requirements-ingestion.txt` | Python dependencies (the second one is only for reproducing the extraction) |

## What you need (by level)

| Level | What it runs | Machine | Install |
|---|---|---|---|
| 1. Local Spark test | the 4 Spark jobs on plain parquet | any laptop; the reference run completed in about 2 minutes on a VM with only 3 GB RAM and 2 cores | Python 3.10 and Java 11 (the versions it was tested with; Java 17 is also supported by Spark 3.5), `pip install -r requirements.txt`, WSL2 on Windows |
| 2. Full lakehouse | MinIO, MySQL, Iceberg REST, Spark, Trino, Airflow on Kubernetes | 16 GB RAM is workable, 12 GB is the lowest the setup script accepts (it warns below that), 32 GB is **not** required. Sum of the pod memory limits is about 10-11 GB, so give Docker Desktop 10-12 GB. Use `mode-etl.ps1` (Trino off) while Spark runs and `mode-full.ps1` to query; these two modes exist to save RAM | Windows, Docker Desktop with Kubernetes, kubectl, PowerShell |
| 3. Text-to-SQL | LLM calls over HTTP, SQL runs on Trino | level 2 must be running (the `oracle` check needs no cluster) | `pip install -r requirements.txt`, your own API key |

Level 2 was run on the author's PC; it has not been tried on a 16 GB machine. Level 1 is the recommended way to check the project.

## Three ways to try it

You need the **core data pack** ([DATA.md](DATA.md)) unzipped in the repository root (it contains `extract/`).

### 1. Local Spark test, no cluster (about 2 minutes)

Linux, macOS or WSL2 with Java 11 or 17.

```bash
pip install -r requirements.txt
bash lakehouse/tests/run_local_test.sh .      # bronze -> silver -> gold -> check
```

Expected last line: `CHECK PASSED: lakehouse tables match the baseline` (every table has the expected row count, VCB 2023 net profit = 33,054.448 billion VND).
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
python eval_t2s.py --backend oracle --set golden.json        # no LLM, no cluster: checks the grader and the question file, expect 31/31
# the next commands need the lakehouse running and the Trino port-forward open (lakehouse/scripts/ops/port-forward.ps1 trino)
export OPENAI_API_KEY=...                                    # your own DeepSeek (or OpenAI-compatible) key
python eval_t2s.py --backend openai --model deepseek-flash --set golden.json
python -m streamlit run app.py                               # UI; type the key in the sidebar
```

On PowerShell set the key with `$env:OPENAI_API_KEY = "..."`. **Never commit a key.** The key is read from the environment or typed in the UI and is not stored anywhere.
Every generated SQL query runs on Trino. The expected answers are frozen in `golden*.json` (field `gold`, taken from the verified data; the `sql` field is only the reference query that produced them), so grading needs no second engine.

**The Ask tab answers both kinds of questions.** Each question is routed automatically: numbers go through Text-to-SQL on Trino (result shown with a chart and CSV download); questions about what the reports *say* (strategy, risks, plans) are answered from excerpts found in `text_chunks` by keyword search, with page citations such as `[VCB 2023 p.13]`; a question that needs both runs both. Nothing extra to install. `python rag.py ask "..."` runs the text part from the command line.

## Results

Data: `vn30_check.py` compares the row count of every Bronze, Silver and Gold table with the expected baseline and fails the Airflow run on any difference.
Before the earlier single-machine prototype was removed, the Silver tables were verified against it cell by cell (0 differing cells).

Text-to-SQL on Trino, execution accuracy; *strict* = same rows and columns, *lenient* = extra columns allowed.

| Model | Dev set (31 questions) strict / lenient | Held-out set (27 questions) strict / lenient |
|---|---|---|
| deepseek-flash | 18 / 31 (all 31 SQL executable) | 17 / 27 (the 4 unanswerable questions are all declined) |
| deepseek-v4-pro | 23 / 30 (all 31 SQL executable) | 16 / 27 (the 4 unanswerable questions are all declined) |
| oracle (reference SQL) | 31 / 31 | 27 / 27 |

## Known limitations

* The test sets are small and written by the authors. The held-out set was looked at while improving the prompt, so it is **not** an independent test.
* BVH: total assets and equity for 2021-2024 are missing. BCM and BVH for 2020 could not be cross-checked. 448 Silver rows are flagged `needs_review`.
* 38 of the 192 ticker-years (32 companies x 6 years) have no PDF at the source. Of the 154 reports processed, 4 produced no text chunks (BID 2021, BVH 2023, STB 2021, STB 2022), so `text_chunks` covers 150 reports.
* The text of about 30 reports lost many Vietnamese diacritics during extraction (OCR language / PDF font problems; numbers were unaffected). Text questions about those reports are unreliable (the search matches words, not meaning); the Ask tab flags them with a warning.
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
