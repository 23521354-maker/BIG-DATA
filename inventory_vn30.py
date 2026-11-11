import csv, json, os, sys
from concurrent.futures import ProcessPoolExecutor
import fitz  # PyMuPDF

HERE = os.path.dirname(os.path.abspath(__file__))
PDF = os.path.join(HERE, "pdf")
CACHE = os.path.join(HERE, "inventory_cache.jsonl")

def scan(path):
    doc = fitz.open(path)
    c = {"text": 0, "low_text": 0, "image": 0, "blank": 0}
    chars_total = 0
    for page in doc:
        n = len(page.get_text().strip())
        chars_total += n
        if n >= 200: c["text"] += 1
        elif n >= 50: c["low_text"] += 1
        elif page.get_images(): c["image"] += 1
        else: c["blank"] += 1
    return {"pages": len(doc), "chars": chars_total, **c}

def job(rel):
    try:
        r = scan(os.path.join(PDF, rel)); r["error"] = ""
    except Exception as e:
        r = {"pages": 0, "chars": 0, "text": 0, "low_text": 0, "image": 0, "blank": 0, "error": str(e)[:80]}
    r["relative_path"] = rel
    return r

if __name__ == "__main__":
    sel = list(csv.DictReader(open(os.path.join(HERE, "selected_files.csv"), encoding="utf-8")))
    done = set()
    if os.path.exists(CACHE):
        done = {json.loads(l)["relative_path"] for l in open(CACHE, encoding="utf-8")}
    todo = [r["relative_path"] for r in sel if r["relative_path"] not in done]
    print(f"done {len(done)}, todo {len(todo)}", flush=True)
    with ProcessPoolExecutor(max(1, (os.cpu_count() or 2) - 1)) as ex, open(CACHE, "a", encoding="utf-8") as f:
        for r in ex.map(job, todo):
            f.write(json.dumps(r) + "\n"); f.flush()
    print("batch finished", flush=True)
