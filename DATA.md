# Data packs

The git repository contains **code only**. The data is shared as two packs; unzip them into the **repository root**
(all scripts find `extract/`, `delta/` and `pdf/` relative to their own location, so the drive or folder name does not matter).

## Pack A - core (about 100 MB, required)

| Folder | Content | Needed for |
|---|---|---|
| `extract/` | `text/*.json` (page text of 154 reports, 67 MB), `financial_indicators.csv`, `cafef_bctc_nam_*.csv`, other extractor outputs | Bronze layer (lakehouse), local test |
| `delta/` | Delta Lake tables of the single-machine pipeline (31 MB) | parity check and the **gold answers** of the Text-to-SQL evaluation (DuckDB reference) |
| `dashboard/` | `fi.json`, `companies.json` | optional dashboard |

Without `extract/` nothing runs. Without `delta/` the lakehouse still runs, but `parity_silver.py` and `eval_t2s.py` cannot compute gold answers.

## Pack B - PDFs (about 2 GB, optional, reference only)

`pdf/<TICKER>/<TICKER>_<YY>CN_BCTN.pdf` - the 154 annual reports of 32 VN30 tickers, 2020-2025 (38 ticker-years are missing at the source, see `missing_files.csv`).
It only shows **which documents were processed**; no step of the lakehouse reads it except the optional upload to MinIO `raw/vn30/pdf/`.
You do not need a copy from us: `python download_vn30.py` downloads exactly these files from Zenodo, and `selected_files.csv` lists every file with its SHA-256.

## Where the data comes from

* **Annual-report PDFs**: Ngo, Phu Thanh (2026). *Vietnam Listed Companies Annual Reports PDF Dataset, 2000-2025*, v1.0.0, Zenodo,
  https://doi.org/10.5281/zenodo.20949551 - license CC BY 4.0. Used here for 32 VN30 tickers, fiscal years 2020-2025.
* **`extract/` text and indicator CSVs**: produced by the extraction scripts in this repo (PDF text, OCR for scanned pages, rule-based extraction).
* **`extract/cafef_*.csv`**: financial statements scraped from CafeF, used only to cross-check the extracted values.
  This is third-party data, therefore it is **not** published in the repository; it is shared inside the course group only. Respect the site's terms if you re-collect it.

## How `extract/` was produced (documentation, optional, slow)

Not required to run the lakehouse. The scripts in the repository root cover these stages; install `requirements-ingestion.txt`
and the Tesseract binary (Vietnamese language pack) before trying any of them.

| Stage | Scripts |
|---|---|
| Get the PDFs | `download_vn30.py` (Zenodo, partial zip download), `inventory_vn30.py` (page/text inventory) |
| Page text and OCR of scanned pages | `dump_text.py`, `locate_pages.py`, `scan_tess.py` (Tesseract), `ppocr_batch.py` / `run_ppocr_batch.ps1` (PaddleOCR, the slow step: logged OCR time adds up to about 18 hours on the author's PC) |
| Financial indicators | `extract_indicators.py` (rule-based), `apply_cafef.py` (cross-check), `derive_ratios.py`, `load_delta.py` (single-machine reference pipeline, now superseded by the Spark jobs but kept for parity) |
| Hand-checked ground truth | `eval_accuracy.py` |

No script for collecting the CafeF tables is included. This part has not been re-run on a clean machine, so the exact order and options are not guaranteed.
