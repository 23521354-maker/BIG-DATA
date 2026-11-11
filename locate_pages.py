import json, glob, re, csv, unicodedata, collections, os
def norm(s):
    s = s.replace("đ","d").replace("Đ","D")
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
NUM = re.compile(r"(?<![\d.,])\d{1,3}(?:[.,]\d{3})+(?![\d])")
KW = {
 "BS": ["can doi ke toan","tong cong tai san","tai san ngan han","no phai tra"],
 "IS": ["ket qua hoat dong","doanh thu thuan","loi nhuan sau thue","loi nhuan truoc thue"],
 "CF": ["luu chuyen tien"],
 "KPI":["chi tieu tai chinh","chi so tai chinh","tinh hinh tai chinh"],
}
rows=[]; secs=[]
for fn in glob.glob("tess_scan/pages_*.jsonl"):
    for l in open(fn,encoding="utf-8"):
        d=json.loads(l); t=norm(d["text"]); secs.append(d["sec"])
        hits={k:sum(w in t for w in ws) for k,ws in KW.items()}
        nn=len(NUM.findall(d["text"]))
        rows.append(dict(file=d["f"],page=d["p"],chars=len(t),nums=nn,**hits))
def kind(r):
    if r["nums"]<10: return ""
    if r["BS"]>=2: return "BS"
    if r["IS"]>=2: return "IS"
    if r["CF"]>=1: return "CF"
    if r["KPI"]>=1: return "KPI"
    return ""
for r in rows: r["kind"]=kind(r)
rows.sort(key=lambda r:(r["file"],r["page"]))
with open("tess_scan/located_pages.csv","w",newline="",encoding="utf-8") as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print("pages scanned",len(rows),"avg sec/page",round(sum(secs)/len(secs),2))
c=collections.Counter(r["kind"] for r in rows); print(dict(c))
loc=[r for r in rows if r["kind"]]
print("located pages",len(loc))
bydoc=collections.defaultdict(list)
for r in rows: bydoc[r["file"]].append(r)
nloc=collections.Counter(r["file"] for r in loc)
print("files with scan pages",len(bydoc),"| with >=1 located",len(nloc),"| zero located",len(bydoc)-len(nloc))
print("located per file: median",sorted(nloc.values())[len(nloc)//2],"max",max(nloc.values()))
# pages with many numbers but no kind (maybe notes / other tables)
num_only=[r for r in rows if r["nums"]>=10 and not r["kind"]]
print("number-dense pages w/o statement keyword",len(num_only))
for k in ("BS","IS"):
    fs={r["file"] for r in loc if r["kind"]==k}; print(k,"files",len(fs))
print("zero-located files (first 25):",[f for f in bydoc if f not in nloc][:25])
print("est PP-OCRv6 hours @45s:",round(len(loc)*45/3600,1),"| number-dense all:",round((len(loc)+len(num_only))*45/3600,1))
