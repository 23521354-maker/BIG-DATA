import os, sys, json, glob, time, statistics
import pymupdf
from multiprocessing import Pool
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "extract", "text")
FORCE = set()
if os.path.exists(os.path.join(BASE, "ocr_batch", "extra_pages.json")) and os.environ.get("REFRESH"):
    FORCE = {f for f, p, t in json.load(open(os.path.join(BASE, "ocr_batch", "extra_pages.json")))}
BUDGET = float(sys.argv[1]) if len(sys.argv) > 1 else 140

def rows_from_items(items):
    # items: (xc, yc, h, x0, text)
    if not items: return []
    items.sort(key=lambda t: t[1])
    hs = [t[2] for t in items if t[2] > 0]
    tol = max(2.0, 0.5 * (statistics.median(hs) if hs else 6))
    rows, cur, cy = [], [], None
    for it in items:
        if cur and abs(it[1] - cy) > tol:
            rows.append(cur); cur = []
        cur.append(it); cy = sum(t[1] for t in cur) / len(cur)
    if cur: rows.append(cur)
    return [" ".join(t[4] for t in sorted(r, key=lambda t: t[3])) for r in rows]

def do_file(f):
    name = os.path.basename(f)[:-4]
    outp = os.path.join(OUT, name + ".json")
    if os.path.exists(outp) and name not in FORCE: return name, "skip"
    pages = []
    try:
        doc = pymupdf.open(f)
        for i, pg in enumerate(doc):
            p = i + 1
            if len(pg.get_text().strip()) >= 50:
                w = pg.get_text("words")
                items = [((a + c) / 2, (b + d) / 2, d - b, a, t) for a, b, c, d, t, *_ in w]
                pages.append({"p": p, "src": "text", "rows": rows_from_items(items)})
            else:
                oj = os.path.join(BASE, "ocr_batch", "pages", f"{name}__p{p}.json")
                if os.path.exists(oj):
                    d = json.load(open(oj, encoding="utf-8"))
                    items = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, b[3] - b[1], b[0], t)
                             for t, b in zip(d["texts"], d["boxes"])] if d.get("boxes") else \
                            [(0, k * 10, 10, 0, t) for k, t in enumerate(d["texts"])]
                    pages.append({"p": p, "src": "ocr", "rows": rows_from_items(items)})
        doc.close()
    except Exception as e:
        return name, "ERR " + str(e)[:80]
    json.dump(pages, open(outp, "w", encoding="utf-8"), ensure_ascii=False)
    return name, f"ok {len(pages)}"

if __name__ == "__main__":
    t0 = time.time()
    files = sorted(glob.glob(os.path.join(BASE, "pdf", "*", "*.pdf")))
    todo = [f for f in files if os.path.basename(f)[:-4] in FORCE or not os.path.exists(os.path.join(OUT, os.path.basename(f)[:-4] + ".json"))]
    print("files", len(files), "todo", len(todo), flush=True)
    with Pool(2) as pool:
        for name, st in pool.imap_unordered(do_file, todo):
            print(name, st, flush=True)
            if time.time() - t0 > BUDGET:
                pool.terminate(); print("budget reached"); break
