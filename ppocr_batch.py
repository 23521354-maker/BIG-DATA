# Batch PP-OCRv6 over located pages. Resumable: re-run to continue. Stops cleanly at --until HH:MM.
import os, sys, csv, json, time, datetime
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "ocr_batch", "pages"); os.makedirs(OUT, exist_ok=True)
LOG = os.path.join(BASE, "ocr_batch", "timings.jsonl")
THREADS = 12
SUS = ["ACB_23","ACB_24","ACB_25","VIB_20","VIB_23","VIB_24","VIB_25","BID_23","MWG_21"]

def todo():
    rows = list(csv.DictReader(open(os.path.join(BASE, "tess_scan", "located_pages.csv"), encoding="utf-8")))
    n = lambda r: int(r["nums"]); kw = lambda r: any(int(r[k]) >= 1 for k in ("BS","IS","CF","KPI"))
    out = []
    for r in rows:
        if r["kind"]: t = 1
        elif (kw(r) and n(r) >= 3) or n(r) >= 10: t = 2
        elif n(r) >= 5: t = 3
        elif any(s in r["file"] for s in SUS) and (kw(r) or n(r) >= 2): t = 4
        else: continue
        out.append((t, r["file"], int(r["page"])))
    out.sort(key=lambda x: (x[0], x[1], x[2]))
    return out

def todo_extra():
    import glob
    paths = {os.path.basename(p)[:-4]: os.path.relpath(p, BASE).replace("\\", "/") for p in glob.glob(os.path.join(BASE, "pdf", "*", "*.pdf"))}
    items = json.load(open(os.path.join(BASE, "ocr_batch", "extra_pages.json")))
    out = [(t, paths[f], p) for f, p, t in items if f in paths]
    out.sort(key=lambda x: (x[0], x[1], x[2]))
    return out

def main():
    until = None
    if "--until" in sys.argv:
        hh, mm = sys.argv[sys.argv.index("--until") + 1].split(":")
        now = datetime.datetime.now()
        until = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        if until <= now: until += datetime.timedelta(days=1)
    import pymupdf
    from paddleocr import PaddleOCR
    ocr = PaddleOCR(lang="vi", use_doc_orientation_classify=False, use_doc_unwarping=False,
                    use_textline_orientation=False, enable_mkldnn=False, cpu_threads=THREADS)
    items = todo_extra() if "--extra" in sys.argv else todo()
    name = lambda f, p: os.path.join(OUT, f"{os.path.basename(f)[:-4]}__p{p}.json")
    left = [i for i in items if not os.path.exists(name(i[1], i[2]))]
    print(f"total {len(items)} | done {len(items)-len(left)} | left {len(left)} | until {until}", flush=True)
    t_start = time.time(); done_now = 0; cur = None; doc = None
    for t, f, p in left:
        if until and datetime.datetime.now() >= until:
            print("Reached stop time. Re-run to continue.", flush=True); break
        try:
            if f != cur:
                if doc: doc.close()
                doc = pymupdf.open(os.path.join(BASE, f)); cur = f
            png = os.path.join(BASE, "ocr_batch", "_tmp.png")
            doc[p-1].get_pixmap(dpi=150).save(png)
            s = time.time(); r = ocr.predict(png)[0]; dt = time.time() - s
            texts = list(r["rec_texts"]); scores = [float(x) for x in r["rec_scores"]]
            boxes = [list(map(int, b)) for b in r["rec_boxes"]] if "rec_boxes" in r else []
            json.dump({"file": f, "page": p, "tier": t, "sec": round(dt, 1), "texts": texts,
                       "scores": scores, "boxes": boxes}, open(name(f, p) + ".tmp", "w", encoding="utf-8"), ensure_ascii=False)
            os.replace(name(f, p) + ".tmp", name(f, p))
            with open(LOG, "a", encoding="utf-8") as lg:
                lg.write(json.dumps({"f": f, "p": p, "t": t, "sec": round(dt, 1), "lines": len(texts)}) + "\n")
            done_now += 1
            if done_now % 10 == 0 or done_now == 1:
                el = time.time() - t_start
                print(f"[{done_now}/{len(left)}] {os.path.basename(f)} p{p} tier{t} {dt:.0f}s | avg {el/done_now:.0f}s/page | ETA {(len(left)-done_now)*el/done_now/3600:.1f}h", flush=True)
        except Exception as e:
            with open(LOG, "a", encoding="utf-8") as lg:
                lg.write(json.dumps({"f": f, "p": p, "error": str(e)[:200]}) + "\n")
            print("ERROR", f, p, str(e)[:120], flush=True)
    print(f"FINISHED this run: {done_now} pages", flush=True)

if __name__ == "__main__":
    main()
