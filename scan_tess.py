import sys, os, json, time, subprocess, glob
import pymupdf
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "tess_scan")
TASKS = os.path.join(OUT, "tasks.json")
DPI = 110
ENV = dict(os.environ, OMP_THREAD_LIMIT="1", TESSDATA_PREFIX=os.path.expanduser("~/tessdata"))

def build_tasks():
    tasks = []
    for f in sorted(glob.glob(os.path.join(BASE, "pdf", "*", "*.pdf"))):
        rel = os.path.relpath(f, BASE).replace("\\", "/")
        try:
            doc = pymupdf.open(f)
        except Exception as e:
            print("ERR", rel, e); continue
        for i, pg in enumerate(doc):
            if len(pg.get_text().strip()) < 50 and pg.get_images():
                tasks.append([rel, i + 1])
        doc.close()
    json.dump(tasks, open(TASKS, "w"))
    print("image pages:", len(tasks))

def worker(k, n, budget):
    t0 = time.time()
    tasks = json.load(open(TASKS))
    outp = os.path.join(OUT, f"pages_{k}.jsonl")
    done = set()
    if os.path.exists(outp):
        for l in open(outp, encoding="utf-8"):
            try:
                d = json.loads(l); done.add((d["f"], d["p"]))
            except Exception: pass
    mine = [t for j, t in enumerate(tasks) if j % n == k and (t[0], t[1]) not in done]
    print(f"worker{k}: remaining {len(mine)}", flush=True)
    cur, doc = None, None
    with open(outp, "a", encoding="utf-8") as fo:
        for rel, p in mine:
            if time.time() - t0 > budget: break
            if rel != cur:
                if doc: doc.close()
                doc = pymupdf.open(os.path.join(BASE, rel)); cur = rel
            s = time.time()
            png = doc[p - 1].get_pixmap(dpi=DPI, colorspace=pymupdf.csGRAY).tobytes("png")
            r = subprocess.run(["tesseract", "stdin", "stdout", "-l", "vie", "--psm", "6"],
                               input=png, capture_output=True, env=ENV)
            txt = r.stdout.decode("utf-8", "ignore")
            fo.write(json.dumps({"f": rel, "p": p, "sec": round(time.time() - s, 2), "text": txt}, ensure_ascii=False) + "\n")
            fo.flush()
    print(f"worker{k}: done this round", flush=True)

if __name__ == "__main__":
    if sys.argv[1] == "build": build_tasks()
    else: worker(int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3]))
