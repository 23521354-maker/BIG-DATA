#!/usr/bin/env bash
# Run the four Spark jobs on your own machine (no Kubernetes): plain parquet instead of Iceberg.
# Linux / macOS / WSL2.  Needs: Java 11 or 17, `pip install -r requirements.txt`, and the core data pack (DATA.md).
#
#   bash lakehouse/tests/run_local_test.sh <data_root>
#
# <data_root> is the folder that contains extract/.
set -euo pipefail
DATA="${1:?usage: run_local_test.sh <data_root>}"
DATA="$(cd "$DATA" && pwd)"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$(command -v python3 || command -v python)"
command -v java >/dev/null || { echo "Java 11 or 17 is required (pyspark 3.5)."; exit 1; }
[ -f "$DATA/extract/financial_indicators.csv" ] || { echo "No extract/financial_indicators.csv under $DATA (see DATA.md)."; exit 1; }

# A symlink keeps spaces in the real path (e.g. "BIG DATA") out of the file:// URI that Spark sees.
WORK="$(mktemp -d)"
ln -s "$DATA" "$WORK/data"
OUT="${VN30_LOCAL_OUT:-$WORK/out}"
export VN30_SRC="file://$WORK/data" VN30_LOCAL_OUT="$OUT"
export SPARK_LOCAL_IP=127.0.0.1 SPARK_LOCAL_HOSTNAME=localhost

for job in bronze silver gold check; do
  echo "== vn30_$job"
  "$PY" "$HERE/spark/vn30_$job.py"
done
echo "LOCAL TEST OK -> $OUT"
