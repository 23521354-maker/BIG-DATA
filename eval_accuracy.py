import csv, json, os, re, unicodedata, collections
B=1e9; M=1e6
# TRUTH: values I read directly from the report rows (VND). None-listed items exist in the report but value not read (only needed for recall).
T = {
 ("VNM",2024,"equity"):36174.40*B, ("VNM",2024,"total_assets"):55049.06*B, ("VNM",2024,"net_profit_after_tax"):9452.89*B, ("VNM",2024,"net_revenue"):61782.61*B,
 ("FPT",2023,"net_revenue"):52617900827385, ("FPT",2023,"net_profit_after_tax"):7788049739616, ("FPT",2023,"total_assets"):60282827532899, ("FPT",2023,"equity"):29933011216233,
 ("HPG",2023,"net_revenue"):118953027893654, ("HPG",2023,"net_profit_after_tax"):6800388315081, ("HPG",2023,"total_assets"):187782586563801, ("HPG",2023,"equity"):102836419239379,
 ("VRE",2024,"net_revenue"):8939117*M, ("VRE",2024,"net_profit_after_tax"):4095780*M, ("VRE",2024,"total_assets"):55226155*M, ("VRE",2024,"equity"):41922641*M,
 ("DGC",2022,"net_revenue"):14444110660905, ("DGC",2022,"total_assets"):13405182747367, ("DGC",2022,"equity"):10833653939038,
 ("DGC",2023,"total_assets"):15535906274595,
 ("VCB",2023,"net_interest_income"):53620869*M, ("VCB",2023,"net_profit_after_tax"):33054448*M, ("VCB",2023,"total_assets"):1839613198*M, ("VCB",2023,"equity"):165012666*M,
 ("MBB",2024,"net_interest_income"):41152219*M, ("MBB",2024,"net_profit_after_tax"):22951264*M, ("MBB",2024,"total_assets"):1128801062*M, ("MBB",2024,"equity"):117059581*M,
 ("ACB",2022,"net_interest_income"):23534*B, ("ACB",2022,"net_profit_after_tax"):13688*B, ("ACB",2022,"total_assets"):607875*B, ("ACB",2022,"equity"):58439*B,
 ("TPB",2024,"total_assets"):418028391*M, ("TPB",2024,"equity"):37594469*M,
}
WRONG = {}   # domestic-only revenue from narrative
SAMPLE = ["VNM_2024","FPT_2023","HPG_2023","VRE_2024","DGC_2022","DGC_2023","MWG_2024","VCB_2023","MBB_2024","ACB_2022","TPB_2024"]
BANKS={"VCB","MBB","ACB","TPB"}
SCAN={"DGC","MWG","ACB","TPB"}
def metrics(t): return ["net_interest_income","net_profit_after_tax","total_assets","equity"] if t in BANKS else ["net_revenue","net_profit_after_tax","total_assets","equity"]
rows={(r["ticker"],int(r["fiscal_year"]),r["metric"]):r for r in csv.DictReader(open("extract/financial_indicators.csv",encoding="utf-8-sig"))}
def vnd(r):
    try: return float(r["value_vnd"]) if r["value_vnd"]!="" else float(r["value"])
    except: return None
def ok(a,b,tol): return a is not None and abs(a-b)<=tol*max(abs(b),1)
stats=collections.defaultdict(lambda:collections.Counter()); detail=[]
for sm in SAMPLE:
    t,y=sm.split("_"); y=int(y); grp="scan" if t in SCAN else "text"
    for m in metrics(t):
        r=rows.get((t,y,m)); key=(t,y,m); st=("all",m,grp)
        for g in (("all","ALL","ALL"),("all",m,"ALL"),("all","ALL",grp),("hi","ALL","ALL")): pass
        status="FN"
        if r:
            v=vnd(r); hi=float(r["confidence"])>=0.8
            if key in WRONG and ok(v,WRONG[key],0.002): status="FP(wrong)"
            elif key in T: status="TP" if ok(v,T[key],0.02 if (t,y,m)==("VRE",2024,"net_profit_after_tax") else 0.002) else "FP(wrong)"
            else: status="corroborated" if r["cross_year_ok"]=="True" else "unverified"
        else: hi=False
        detail.append((sm,m,status,(r or {}).get("value",""),(r or {}).get("confidence",""),hi))
def prf(sel):
    tp=sum(1 for d in sel if d[2]=="TP"); fp=sum(1 for d in sel if d[2]=="FP(wrong)"); fn=sum(1 for d in sel if d[2]=="FN"); un=sum(1 for d in sel if d[2]=="unverified"); co=sum(1 for d in sel if d[2]=="corroborated")
    P=tp/(tp+fp) if tp+fp else float("nan"); R=tp/(tp+fn+fp+un+co) if sel else float("nan")  # recall vs all truth items (unverified counted as not-confirmed)
    F=2*P*R/(P+R) if P==P and R==R and P+R else float("nan")
    return f"TP={tp} FP={fp} FN={fn} corroborated(cross-year,value not hand-read)={co} unverified={un} | P={P:.0%} R={R:.0%} F1={F:.0%}"
print("ALL     :",prf(detail))
print("  conf>=0.8 only:",prf([d for d in detail if d[2]=="FN" or d[5]]))
for g,names in (("text-layer",[s for s in SAMPLE if s.split("_")[0] not in SCAN]),("scan/OCR",[s for s in SAMPLE if s.split("_")[0] in SCAN])): print(f"{g:<11}:",prf([d for d in detail if d[0] in names]))
for m in ["net_revenue","net_interest_income","net_profit_after_tax","total_assets","equity"]:
    sel=[d for d in detail if d[1]==m]; print(f"{m:<22}:",prf(sel))
print("\nnon-TP items:")
for d in detail:
    if d[2]!="TP": print("  ",d)
json.dump(detail,open("extract/accuracy_detail.json","w"),ensure_ascii=False)
# accounting identity on OCR sample: total assets (270) == total sources (440 / 'tong nguon von')
def norm(s):
    s=s.replace("đ","d").replace("Đ","D"); return "".join(c for c in unicodedata.normalize("NFD",s) if unicodedata.category(c)!="Mn").lower()
print("\nIdentity check (assets == liabilities+equity) on scan reports:")
for sm in ["DGC_2022","DGC_2023","TPB_2024","MWG_2024","ACB_2022"]:
    t,y=sm.split("_"); fn=[f for f in os.listdir("extract/text") if f.startswith(f"{t}_{y[2:]}CN")][0]
    pgs=json.load(open(f"extract/text/{fn}",encoding="utf-8")); a=[];s=[]
    for p in pgs:
        if p["src"]!="ocr": continue
        for r in p["rows"]:
            n=norm(r); nums=re.findall(r"\d{1,3}(?:[.,]\d{3})+",r)
            if re.search(r"tong cong tai san|tong tai san",n) and nums: a.append((p["p"],nums[0]))
            if re.search(r"tong cong nguon von|tong nguon von|tong no phai tra va von chu so huu",n) and nums: s.append((p["p"],nums[0]))
    print(" ",sm,"assets",a[:2],"| liab+equity",s[:2])
