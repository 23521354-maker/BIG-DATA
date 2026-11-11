import csv, hashlib, os, sys, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from remotezip import RemoteZip

BASE = "https://zenodo.org/records/20949551/files/"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "pdf")
TICKERS = set("ACB BID CTG HDB LPB MBB SHB SSB STB TCB TPB VCB VIB VPB BCM VHM VIC VRE "
              "MSN MWG SAB VNM GAS PLX POW HPG GVR DGC SSI BVH FPT VJC".split())
YEARS = range(2020, 2026)

def fetch(name):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        urllib.request.urlretrieve(f"{BASE}{name}?download=1", p)
    return p

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

rows = list(csv.DictReader(open(fetch("file_index_full.csv"), encoding="utf-8-sig")))
fetch("checksums_pdf_sha256.csv")
sel = [r for r in rows if r["ticker_folder"] in TICKERS and int(r["year_full"]) in YEARS]
have = {(r["ticker_folder"], int(r["year_full"])) for r in sel}
with open(os.path.join(HERE, "missing_files.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["ticker", "year"])
    for t in sorted(TICKERS):
        for y in YEARS:
            if (t, y) not in have: w.writerow([t, y])
with open(os.path.join(HERE, "selected_files.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys()); w.writeheader(); w.writerows(sel)
print(f"selected {len(sel)} files", flush=True)

by_zip = defaultdict(list)
for r in sel: by_zip[r["archive_period"]].append(r)
results = {"ok": 0, "skip": 0, "bad": []}

def work(url, chunk):
    with RemoteZip(url) as z:
        index = {}
        for n in z.namelist():
            index.setdefault(n.split("/", 1)[-1] if n.count("/") > 1 else n, n)
        for r in chunk:
            dest = os.path.join(OUT, r["relative_path"])
            if os.path.exists(dest) and sha256(dest) == r["sha256"]:
                results["skip"] += 1; continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            try:
                member = index.get(r["relative_path"]) or next(n for n in z.namelist() if n.endswith(r["relative_path"]))
                z.extract(member, os.path.join(HERE, "_tmp"))
                os.replace(os.path.join(HERE, "_tmp", member), dest)
                if sha256(dest) == r["sha256"]: results["ok"] += 1; print("ok ", r["relative_path"], flush=True)
                else: results["bad"].append(r["relative_path"]); print("BAD", r["relative_path"], flush=True)
            except Exception as e:
                results["bad"].append(r["relative_path"]); print("ERR", r["relative_path"], e, flush=True)

for period, items in sorted(by_zip.items()):
    url = f"{BASE}vn_bctn_{period}.zip?download=1"
    print(f"== {period}: {len(items)} files", flush=True)
    chunks = [items[i::6] for i in range(6)]
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda c: work(url, c), chunks))
print("DONE", results, flush=True)
