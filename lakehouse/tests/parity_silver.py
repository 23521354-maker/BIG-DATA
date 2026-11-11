"""Parity check: Silver tables written by Spark (parquet test output) vs the old Delta tables (delta/).
Usage: python tests/parity_silver.py <silver_parquet_dir> <delta_dir>
Compares every column except ingested_at; floats within 1e-9 relative. Exit code 1 on any difference."""
import sys, math, os
import pandas as pd
from deltalake import DeltaTable

silver_dir, delta_dir = sys.argv[1], sys.argv[2]
KEYS = {"financial_indicators": ["ticker", "fiscal_year", "metric", "method", "source", "raw_row"],
        "text_chunks": ["chunk_id"], "companies": ["ticker"], "metric_catalog": ["metric"]}
bad = 0
for name, keys in KEYS.items():
    a = pd.read_parquet(os.path.join(silver_dir, "vn30_silver", name))
    b = DeltaTable(os.path.join(delta_dir, name)).to_pandas()
    cols = [c for c in b.columns if c != "ingested_at"]
    a, b = a[cols].copy(), b[cols].copy()
    if len(a) != len(b):
        print(f"{name}: row count differs {len(a)} vs {len(b)}"); bad += 1
    a = a.sort_values(keys, kind="mergesort").reset_index(drop=True)
    b = b.sort_values(keys, kind="mergesort").reset_index(drop=True)
    diffs = 0
    for c in cols:
        for x, y in zip(a[c], b[c]):
            xn, yn = pd.isna(x), pd.isna(y)
            if xn and yn:
                continue
            if xn != yn:
                diffs += 1; continue
            if isinstance(x, float) or isinstance(y, float):
                if not math.isclose(float(x), float(y), rel_tol=1e-9, abs_tol=1e-9):
                    diffs += 1
            elif x != y:
                diffs += 1
    print(f"{name}: rows {len(a)} | differing cells {diffs}")
    bad += diffs
print("PARITY OK" if bad == 0 else f"PARITY FAILED ({bad})")
# os._exit: skip interpreter teardown, which can abort (signal 6) after deltalake + pyarrow were loaded
sys.stdout.flush()
os._exit(1 if bad else 0)
