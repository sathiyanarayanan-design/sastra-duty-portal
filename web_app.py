"""
SASTRA SoME End Semester Examination Duty Portal
=================================================
Files required in GitHub repo:
  1. Faculty_Master.xlsx  — faculty list + designation + optional valuation date cols (V1..V5)
  2. Offline_Duty.xlsx    — offline exam slots  (col A: Date | col B: FN/AN | col C: count)
  3. Online_Duty.xlsx     — online exam slots   (col A: Date | col B: FN/AN | col C: count)
  4. sastra_logo.png      — university logo (optional)
  5. Willingness.xlsx     — faculty willingness collected via this portal
                            (download CSV from Admin tab, save as xlsx, upload to GitHub)

Login credentials:
  Faculty portal : SASTRA / SASTRA
  Admin panel    : sathya
"""

import os, datetime, warnings, calendar as calmod, urllib.parse
from collections import defaultdict
import numpy as np
import pandas as pd
import streamlit as st
import altair as alt

try:
    from scipy.optimize import milp, LinearConstraint, Bounds
    from scipy.sparse import csc_matrix
    SCIPY_OK = True
except ImportError:
    SCIPY_OK = False

warnings.filterwarnings("ignore")

# ─── File names ──────────────────────────────────────────────── #
FACULTY_FILE      = "Faculty_Master.xlsx"
OFFLINE_FILE      = "Offline_Duty.xlsx"
ONLINE_FILE       = "Online_Duty.xlsx"
WILLINGNESS_FILE  = "Willingness.xlsx"
LOGO_FILE         = "sastra_logo.png"
FINAL_ALLOC_FILE  = "Final_Allocation.xlsx"
ALLOC_REPORT_FILE = "Allocation_Report.xlsx"

# ─── Designation rules ───────────────────────────────────────── #
# (min_duties, max_duties, allowed_types)
DESIG_RULES = {
    "P":   (1, 1, ["Online"]),
    "ACP": (2, 3, ["Online", "Offline"]),
    "SAP": (3, 3, ["Offline"]),
    "AP3": (3, 3, ["Offline"]),
    "AP2": (3, 3, ["Offline"]),
    "TA":  (3, 3, ["Offline"]),
    "RA":  (4, 4, ["Offline"]),
}
DUTY_STRUCTURE = {"P":3,"ACP":5,"SAP":7,"AP3":7,"AP2":7,"TA":9,"RA":9}

W_EXACT=100; W_FLIP=70; W_ADJ=40; W_ACP_ONLINE=60; W_NON_SUB=5; PENALTY=30

# ─── Page config ─────────────────────────────────────────────── #
st.set_page_config(page_title="SASTRA Duty Portal", layout="wide")
st.markdown("""
<style>
.stApp{background:#f4f7fb}
.main .block-container{max-width:1200px;padding-top:1.2rem;padding-bottom:1.5rem}
.card{background:linear-gradient(180deg,#fff 0%,#f8fafc 100%);border:1px solid #dbe3ef;
      border-radius:14px;padding:16px 18px;box-shadow:0 10px 24px rgba(15,23,42,.08);margin-bottom:12px}
.panel{background:#fff;border:1px solid #e2e8f0;border-radius:14px;
       padding:14px 16px;box-shadow:0 8px 20px rgba(15,23,42,.06);margin-bottom:10px}
.card-title{font-size:1.08rem;font-weight:700;color:#0f172a;margin-bottom:.2rem}
.card-sub{font-size:.93rem;color:#334155;margin-bottom:0}
.sec-title{font-size:1rem;font-weight:700;color:#0b3a67;margin-bottom:.35rem}
.stButton>button{border-radius:10px;border:1px solid #cbd5e1;font-weight:600}
.stDownloadButton>button{border-radius:10px;font-weight:600}
.blink{font-weight:700;color:#800000;padding:10px 12px;border:2px solid #800000;
       background:#fffaf5;border-radius:6px;animation:pulse 2.4s ease-in-out infinite}
@keyframes pulse{0%{opacity:1}50%{opacity:.35}100%{opacity:1}}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════ #
#                     UTILITY FUNCTIONS                          #
# ═══════════════════════════════════════════════════════════════ #
def clean(x):
    return str(x).strip().lower()

def normalize_session(v):
    t = str(v).strip().upper()
    if t in {"FN","FORENOON","MORNING","AM"}: return "FN"
    if t in {"AN","AFTERNOON","EVENING","PM"}: return "AN"
    return t

def fmt_day(val):
    dt = pd.to_datetime(val, dayfirst=True, errors="coerce")
    return f"{dt.strftime('%d-%m-%Y')} ({dt.strftime('%A')})" if pd.notna(dt) else str(val)

def valuation_dates_for(row):
    return sorted({pd.to_datetime(row[c], dayfirst=True).date()
                   for c in ["V1","V2","V3","V4","V5"]
                   if c in row.index and pd.notna(row[c])})

def qp_dates_for(row):
    return sorted({pd.to_datetime(row[c], dayfirst=True, errors="coerce").strftime("%d-%m-%Y")
                   for c in row.index
                   if "QP" in str(c).upper() and "DATE" in str(c).upper() and pd.notna(row[c])
                   and pd.notna(pd.to_datetime(row[c], dayfirst=True, errors="coerce"))})

def fac_mask(df, sel_clean):
    if df.empty: return pd.Series([], dtype=bool)
    cols = [c for c in df.columns if "name" in c.lower() or "faculty" in c.lower()]
    mask = pd.Series([False]*len(df), index=df.index)
    for c in cols: mask = mask | (df[c].astype(str).apply(clean)==sel_clean)
    return mask

def wa_link(phone, msg):
    p = str(phone).strip().replace("+","").replace(" ","").replace("-","")
    return f"https://wa.me/{p}?text={urllib.parse.quote(msg)}"

def build_msg(name, will, val, inv, qp, pct):
    return "\n".join([f"Dear {name},","","Examination Duty Details:","",
                      "1) Invigilation Dates (Final Allotment):",*(inv or ["Not allotted yet"]),"",
                      "2) Valuation Dates (Full Day):",*(val or ["Not available"]),"",
                      "3) QP Feedback Dates:",*(qp or ["Not available"]),"",
                      f"Willingness Accommodation: {pct}","",
                      "- SASTRA SoME Examination Committee"])

def render_header(logo=True):
    if logo and os.path.exists(LOGO_FILE):
        _,c2,_ = st.columns([2,1,2])
        with c2: st.image(LOGO_FILE, width=180)
    st.markdown("<h2 style='text-align:center;margin-bottom:.25rem'>"
                "SASTRA SoME End Semester Examination Duty Portal</h2>", unsafe_allow_html=True)
    st.markdown("<h4 style='text-align:center;margin-top:0'>"
                "School of Mechanical Engineering</h4>", unsafe_allow_html=True)
    st.markdown("---")


# ═══════════════════════════════════════════════════════════════ #
#               PARSE DUTY FILE (shared helper)                  #
# ═══════════════════════════════════════════════════════════════ #
def parse_duty_file(filepath, duty_type):
    """
    Read Offline_Duty.xlsx or Online_Duty.xlsx.
    Expected: col A = Date, col B = FN/AN, col C = count required.
    Header row is auto-detected and skipped if present.
    Returns list of slot dicts.
    """
    if not os.path.exists(filepath):
        return []
    try:
        raw = pd.read_excel(filepath, header=None)
    except Exception:
        return []
    # Skip row 0 if it is not a date (i.e. it is a header)
    try:
        pd.to_datetime(raw.iloc[0, 0])
        start = 0
    except Exception:
        start = 1
    slots = []
    for i in range(start, len(raw)):
        row  = raw.iloc[i]
        d    = row.iloc[0]
        sess = row.iloc[1] if len(row) > 1 else None
        req  = row.iloc[2] if len(row) > 2 else 1
        if pd.isna(d): continue
        sn = normalize_session(sess)
        if sn not in ("FN","AN"): continue
        try:    date = pd.to_datetime(d).date()
        except: continue
        try:    required = max(int(float(req)), 0)
        except: required = 1
        slots.append({"date":date,"session":sn,"required":required,"type":duty_type})
    return slots


@st.cache_data
def load_slots(off_path, on_path):
    """Cache duty slots from Offline_Duty.xlsx and Online_Duty.xlsx."""
    def to_df(slots):
        if not slots:
            df = pd.DataFrame(columns=["Date","Session","Required"])
            df["Date"] = pd.to_datetime(df["Date"])
            return df
        df = pd.DataFrame(slots)
        df["Date"]     = pd.to_datetime(df["date"], errors="coerce")
        df["Session"]  = df["session"]
        df["Required"] = df["required"].astype(int)
        return df[["Date","Session","Required"]]
    return to_df(parse_duty_file(off_path,"Offline")), to_df(parse_duty_file(on_path,"Online"))


# ═══════════════════════════════════════════════════════════════ #
#               WILLINGNESS FILE FUNCTIONS                       #
# ═══════════════════════════════════════════════════════════════ #
def load_willingness():
    """
    Load Willingness.xlsx from GitHub repo.
    Scans all sheets for one containing Faculty | Date | Session columns.
    Falls back to renaming first 3 columns of first sheet.
    """
    if not os.path.exists(WILLINGNESS_FILE):
        return pd.DataFrame(columns=["Faculty","Date","Session","FacultyClean"])
    try:
        xl = pd.ExcelFile(WILLINGNESS_FILE)
        df = None
        for sh in xl.sheet_names:
            c = xl.parse(sh); c.columns = c.columns.str.strip()
            if {"Faculty","Date","Session"}.issubset(set(c.columns)):
                df = c[["Faculty","Date","Session"]].copy(); break
        if df is None:
            c = xl.parse(xl.sheet_names[0]); c.columns = c.columns.str.strip()
            if len(c.columns) >= 3:
                c = c.rename(columns={c.columns[0]:"Faculty",c.columns[1]:"Date",c.columns[2]:"Session"})
                df = c[["Faculty","Date","Session"]].copy()
            else:
                df = pd.DataFrame(columns=["Faculty","Date","Session"])
    except Exception:
        df = pd.DataFrame(columns=["Faculty","Date","Session"])
    df["Faculty"] = df["Faculty"].astype(str).str.strip()
    df["Date"]    = df["Date"].astype(str).str.strip()
    df["Session"] = df["Session"].astype(str).str.strip().str.upper()
    df["FacultyClean"] = df["Faculty"].apply(clean)
    return df.dropna(subset=["Faculty"]).reset_index(drop=True)


def get_all_willingness():
    """Committed Willingness.xlsx + new in-session submissions combined."""
    committed = load_willingness().drop(columns=["FacultyClean"], errors="ignore")
    pending   = st.session_state.get("pending_submissions",
                                     pd.DataFrame(columns=["Faculty","Date","Session"]))
    combined  = pd.concat([committed, pending], ignore_index=True)
    combined  = combined.drop_duplicates(subset=["Faculty","Date","Session"])
    combined["FacultyClean"] = combined["Faculty"].apply(clean)
    return combined


def save_submission(faculty_name, slots):
    """Store new willingness in session state."""
    new_rows = pd.DataFrame([
        {"Faculty":faculty_name,
         "Date":   item["Date"].strftime("%d-%m-%Y"),
         "Session":item["Session"]}
        for item in slots
    ])
    if "pending_submissions" not in st.session_state:
        st.session_state.pending_submissions = pd.DataFrame(columns=["Faculty","Date","Session"])
    st.session_state.pending_submissions = pd.concat(
        [st.session_state.pending_submissions, new_rows], ignore_index=True)


# ═══════════════════════════════════════════════════════════════ #
#                    CALENDAR HEATMAP                            #
# ═══════════════════════════════════════════════════════════════ #
def demand_cat(r):
    if r==0: return "No Duty"
    if r<3:  return "Low (<3)"
    if r<=7: return "Medium (3-7)"
    return "High (>7)"

def calendar_frame(duty_df, val_dates, year, month):
    sg   = duty_df.groupby(["Date","Session"],as_index=False)["Required"].sum()
    dmap = {(d.date(),s):int(r) for d,s,r in zip(sg["Date"],sg["Session"],sg["Required"])}
    ms   = pd.Timestamp(year=year,month=month,day=1)
    fw   = ms.weekday()
    WD   = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    rows = []
    for dt in pd.date_range(ms, ms+pd.offsets.MonthEnd(0), freq="D"):
        wk = ((dt.day+fw-1)//7)+1
        do = dt.date()
        for sess in ["FN","AN"]:
            req = dmap.get((do,sess),0)
            cat = "Valuation Locked" if do in val_dates else demand_cat(req)
            rows.append({"Date":dt,"Week":wk,"Weekday":WD[dt.weekday()],
                         "DayNum":dt.day,"Session":sess,"Required":req,
                         "Category":cat,"DateLabel":dt.strftime("%d-%m-%Y")})
    return pd.DataFrame(rows)

def render_calendar(duty_df, val_dates, title):
    st.markdown(f"#### {title}")
    if duty_df.empty: st.info("No slot data available."); return
    months = sorted({(d.year,d.month) for d in duty_df["Date"]})
    cscale = alt.Scale(
        domain=["No Duty","Low (<3)","Medium (3-7)","High (>7)","Valuation Locked"],
        range =["#ececec","#2ca02c","#f1c40f","#d62728","#ff69b4"])
    st.markdown("**Legend:** ⬜ No Duty &nbsp;🟩 Low (<3) &nbsp;🟨 Medium (3-7) "
                "&nbsp;🟥 High (>7) &nbsp;🩷 Valuation Locked")
    for yr,mo in months:
        frame = calendar_frame(duty_df, set(val_dates), yr, mo)
        st.markdown(f"**{calmod.month_name[mo]} {yr}**")
        base = alt.Chart(frame).encode(
            x=alt.X("Weekday:N",sort=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"],title=""),
            xOffset=alt.XOffset("Session:N",sort=["FN","AN"]),
            y=alt.Y("Week:O",sort="ascending",title=""),
            tooltip=[alt.Tooltip("DateLabel:N",title="Date"),
                     alt.Tooltip("Session:N",  title="Session"),
                     alt.Tooltip("Required:Q", title="Demand"),
                     alt.Tooltip("Category:N", title="Category")])
        rect     = base.mark_rect(stroke="white").encode(
            color=alt.Color("Category:N",scale=cscale,legend=alt.Legend(title="Legend")))
        day_text = (alt.Chart(frame[frame["Session"]=="FN"])
                    .mark_text(color="black",fontSize=11,dy=-6)
                    .encode(x=alt.X("Weekday:N",sort=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]),
                            y=alt.Y("Week:O",sort="ascending"),text=alt.Text("DayNum:Q")))
        st.altair_chart((rect+day_text).properties(height=230),use_container_width=True)
        st.caption("Left half = FN  |  Right half = AN")


# ═══════════════════════════════════════════════════════════════ #
#              MILP OPTIMIZER  (HiGHS via scipy)                 #
# ═══════════════════════════════════════════════════════════════ #
def run_optimizer(log_box):
    log_lines = []
    def log(m=""): log_lines.append(m); log_box.code("\n".join(log_lines), language="text")

    log("="*62)
    log("  SASTRA SoME Duty Optimizer  (HiGHS MILP)")
    log("="*62)

    # 1. Faculty
    fr = pd.read_excel(FACULTY_FILE); fr.columns = fr.columns.str.strip()
    fr.rename(columns={fr.columns[0]:"Name",fr.columns[1]:"Designation"},inplace=True)
    ALL_FAC = [str(r["Name"]).strip() for _,r in fr.iterrows()]
    FAC_IDX = {n:i for i,n in enumerate(ALL_FAC)}
    N_FAC   = len(ALL_FAC)
    fac_d   = {str(r["Name"]).strip(): (str(r["Designation"]).strip().upper()
               if str(r["Designation"]).strip().upper() in DESIG_RULES else "TA")
               for _,r in fr.iterrows()}
    dgroups = defaultdict(list)
    for n,d in fac_d.items(): dgroups[d].append(n)
    log(f"\n  Faculty loaded     : {N_FAC}")

    # 2. Willingness
    w = get_all_willingness().drop(columns=["FacultyClean"],errors="ignore")
    if not w.empty:
        w["Date"]    = pd.to_datetime(w["Date"],dayfirst=True,errors="coerce")
        w["Session"] = w["Session"].astype(str).str.strip().str.upper()
        w = w.dropna(subset=["Date"])
    submitted = set(w["Faculty"].str.strip().unique()) if not w.empty else set()
    non_sub   = [n for n in ALL_FAC if n not in submitted]
    log(f"  Willingness loaded : {len(submitted)} submitted  |  {len(non_sub)} not submitted")

    # 3. Slots
    log("")
    for fp,dt in [(OFFLINE_FILE,"Offline"),(ONLINE_FILE,"Online")]:
        log(f"  {dt:8} file : {'✓ '+fp if os.path.exists(fp) else '✗ MISSING — '+fp}")
    s_off = parse_duty_file(OFFLINE_FILE,"Offline")
    s_on  = parse_duty_file(ONLINE_FILE, "Online")
    ALL_S = s_off + s_on
    NS    = len(ALL_S)
    log(f"  Slots parsed       : {NS}  ({len(s_off)} offline + {len(s_on)} online)")
    if NS == 0:
        raise RuntimeError(
            "No exam slots found.\n"
            "Ensure Offline_Duty.xlsx and Online_Duty.xlsx are in your GitHub repo.\n"
            "Each file: col A=Date, col B=FN or AN, col C=invigilators required.")
    log(f"  Total assignments  : {sum(s['required'] for s in ALL_S)}")

    # 4. Willingness expansion
    fexp = defaultdict(dict)
    for _,row in w.iterrows():
        n = str(row.get("Faculty","")).strip()
        if n not in FAC_IDX: continue
        dt2  = row["Date"].date()
        sess = str(row["Session"]).strip().upper()
        al   = DESIG_RULES[fac_d.get(n,"TA")][2]
        for tp in al:
            k=(dt2,sess,tp); fexp[n][k]=max(fexp[n].get(k,0),W_EXACT)
        if fac_d.get(n)=="ACP":
            for s2 in ["FN","AN"]:
                k=(dt2,s2,"Online"); fexp[n][k]=max(fexp[n].get(k,0),W_ACP_ONLINE)
    for n in list(fexp):
        for (dt2,sess,tp),sc in list(fexp[n].items()):
            if sc<W_FLIP: continue
            opp="AN" if sess=="FN" else "FN"
            k=(dt2,opp,tp); fexp[n][k]=max(fexp[n].get(k,0),W_FLIP)
    for n in list(fexp):
        for (dt2,sess,tp),sc in list(fexp[n].items()):
            if sc<W_FLIP: continue
            for delta in [-1,+1]:
                adj=dt2+datetime.timedelta(days=delta)
                for s2 in ["FN","AN"]:
                    k=(adj,s2,tp); fexp[n][k]=max(fexp[n].get(k,0),W_ADJ)
    for n in non_sub:
        al=DESIG_RULES[fac_d.get(n,"TA")][2]
        for s in ALL_S:
            if s["type"] in al:
                k=(s["date"],s["session"],s["type"])
                if k not in fexp[n]: fexp[n][k]=W_NON_SUB

    # 5. Build MILP
    def v(f,s): return f*NS+s
    NV=N_FAC*NS; c=np.zeros(NV); lb=np.zeros(NV); ub=np.ones(NV)
    for fi,fn in enumerate(ALL_FAC):
        al=DESIG_RULES[fac_d[fn]][2]; hs=fn in submitted
        for si,sl in enumerate(ALL_S):
            if sl["type"] not in al: ub[v(fi,si)]=0.0; continue
            k=(sl["date"],sl["session"],sl["type"]); sc=fexp[fn].get(k,0)
            if sc>0: c[v(fi,si)]=-float(sc)
            elif hs: c[v(fi,si)]=float(PENALTY)

    rA,cA,dA,blo,bhi=[],[],[],[]; nc=[0]
    def ac(vids,coeffs,lo,hi):
        for vi,co in zip(vids,coeffs): rA.append(nc[0]);cA.append(vi);dA.append(float(co))
        blo.append(float(lo));bhi.append(float(hi));nc[0]+=1

    on_i =[i for i,s in enumerate(ALL_S) if s["type"]=="Online"]
    off_i=[i for i,s in enumerate(ALL_S) if s["type"]=="Offline"]

    for si,sl in enumerate(ALL_S):
        ac([v(f,si) for f in range(N_FAC)],[1]*N_FAC,sl["required"],sl["required"])
    for fi,fn in enumerate(ALL_FAC):
        dr=DESIG_RULES[fac_d[fn]]; ac([v(fi,s) for s in range(NS)],[1]*NS,dr[0],dr[1])
    dt_tp=defaultdict(list)
    for si,sl in enumerate(ALL_S): dt_tp[(sl["date"],sl["type"])].append(si)
    for fi in range(N_FAC):
        for sil in dt_tp.values():
            if len(sil)>1: ac([v(fi,si) for si in sil],[1]*len(sil),0,1)
    for fn in dgroups["P"]:
        fi=FAC_IDX[fn]
        if on_i: ac([v(fi,si) for si in on_i],[1]*len(on_i),1,1)
    for fn in dgroups["ACP"]:
        fi=FAC_IDX[fn]
        if on_i:  ac([v(fi,si) for si in on_i], [1]*len(on_i), 1,len(on_i))
        if off_i: ac([v(fi,si) for si in off_i],[1]*len(off_i),1,len(off_i))

    A=csc_matrix((dA,(rA,cA)),shape=(nc[0],NV))
    log(f"\n  Variables : {NV}  |  Constraints : {nc[0]}")
    log("  Solving HiGHS MILP (time limit 300 s)...")
    res=milp(c=c,constraints=LinearConstraint(A,blo,bhi),
             integrality=np.ones(NV),bounds=Bounds(lb=lb,ub=ub),
             options={"disp":False,"time_limit":300})
    log(f"  Status : {res.message}")

    # 6. Extract solution
    def tag(fn,k,sc):
        if fn in non_sub:        return "Auto-Assigned"
        if sc>=W_EXACT:          return "Willingness-Exact"
        if sc>=W_ACP_ONLINE:     return "Willingness-ACPOnline"
        if sc>=W_FLIP:           return "Willingness-SessionFlip"
        if sc>=W_ADJ:            return "Willingness-±1Day"
        if sc==W_NON_SUB:        return "Auto-Assigned"
        return "OR-Assigned"

    assigned=[]
    if res.status in (0,1):
        x=np.round(res.x).astype(int)
        for fi,fn in enumerate(ALL_FAC):
            for si,sl in enumerate(ALL_S):
                if x[v(fi,si)]==1:
                    k=(sl["date"],sl["session"],sl["type"]); sc=fexp[fn].get(k,0)
                    assigned.append({"Name":fn,"Date":sl["date"],"Session":sl["session"],
                                     "Type":sl["type"],"Allocated_By":tag(fn,k,sc)})
        method="MILP Optimal (HiGHS)"
    else:
        log("  ⚠ MILP infeasible — greedy fallback...")
        method="Greedy Fallback"
        ac2=defaultdict(int); ud=defaultdict(set)
        def rem(n): return DESIG_RULES[fac_d[n]][0]-ac2[n]
        def ok_t(n,t): return t in DESIG_RULES[fac_d[n]][2]
        def ok_d(n,d,t): return (d,t) not in ud[n]
        for sl in sorted(ALL_S,key=lambda s:-s["required"]):
            d2,s2,r2,t2=sl["date"],sl["session"],sl["required"],sl["type"]
            k=(d2,s2,t2)
            scored=sorted([(n,fexp[n].get(k,0)) for n in ALL_FAC
                           if ok_t(n,t2) and rem(n)>0 and ok_d(n,d2,t2)],
                          key=lambda x:(-x[1],ac2[x[0]]))
            for fn,sc in scored[:r2]:
                ac2[fn]+=1; ud[fn].add((d2,t2))
                assigned.append({"Name":fn,"Date":d2,"Session":s2,"Type":t2,
                                 "Allocated_By":tag(fn,(d2,s2,t2),sc)})
        for fn in ALL_FAC:
            for sl in sorted(ALL_S,key=lambda s:s["date"]):
                if rem(fn)<=0: break
                d2,s2,t2=sl["date"],sl["session"],sl["type"]
                if not ok_t(fn,t2) or not ok_d(fn,d2,t2): continue
                ac2[fn]+=1; ud[fn].add((d2,t2))
                assigned.append({"Name":fn,"Date":d2,"Session":s2,"Type":t2,"Allocated_By":"Gap-Fill"})

    # 7. Build output
    alloc=pd.DataFrame(assigned)
    if alloc.empty: raise RuntimeError("No assignments produced. Check input files.")
    alloc["Date"]=pd.to_datetime(alloc["Date"]).dt.strftime("%d-%m-%Y")
    alloc=alloc.sort_values(["Date","Session","Name"]).reset_index(drop=True)
    if "Sl.No" not in alloc.columns: alloc.insert(0,"Sl.No",alloc.index+1)

    sumrows=[]
    for fn in ALL_FAC:
        d2=fac_d[fn]; dr=DESIG_RULES[d2]; rf=alloc[alloc["Name"]==fn]; ab=rf["Allocated_By"]
        sumrows.append({"Name":fn,"Designation":d2,
            "Submitted":"Yes" if fn in submitted else "No",
            "Required_Duties":dr[0],"Assigned_Duties":len(rf),
            "Willingness_Total":int((ab=="Willingness-Exact").sum())+int((ab=="Willingness-ACPOnline").sum())
                                +int((ab=="Willingness-SessionFlip").sum())+int((ab=="Willingness-±1Day").sum()),
            "Exact_Match":int((ab=="Willingness-Exact").sum()),
            "ACP_Online":int((ab=="Willingness-ACPOnline").sum()),
            "Session_Flip":int((ab=="Willingness-SessionFlip").sum()),
            "Adj_Day":int((ab=="Willingness-±1Day").sum()),
            "Auto_Assigned":int(ab.isin(["Auto-Assigned","OR-Assigned","Gap-Fill"]).sum()),
            "Online":int((rf["Type"]=="Online").sum()),
            "Offline":int((rf["Type"]=="Offline").sum()),
            "Gap":max(dr[0]-len(rf),0)})
    sumdf=pd.DataFrame(sumrows)

    slotrows=[]
    for sl in ALL_S:
        ds=pd.Timestamp(sl["date"]).strftime("%d-%m-%Y")
        na=len(alloc[(alloc["Date"]==ds)&(alloc["Session"]==sl["session"])&(alloc["Type"]==sl["type"])])
        slotrows.append({"Date":ds,"Session":sl["session"],"Type":sl["type"],
                         "Required":sl["required"],"Assigned":na,
                         "Status":"✓" if na>=sl["required"] else f"✗ short {sl['required']-na}"})
    slotdf=pd.DataFrame(slotrows)

    desigrows=[]
    for d2 in DESIG_RULES:
        sub2=sumdf[sumdf["Designation"]==d2]
        if sub2.empty: continue
        on=int(sub2["Online"].sum()); of=int(sub2["Offline"].sum()); dr=DESIG_RULES[d2]
        desigrows.append({"Designation":d2,"Faculty_Count":len(sub2),"Duties_Per_Person":dr[0],
                          "Total_Required":dr[0]*len(sub2),"Total_Assigned":on+of,
                          "Willingness_Matched":int(sub2["Willingness_Total"].sum()),
                          "Auto_Assigned":int(sub2["Auto_Assigned"].sum()),
                          "Online":on,"Offline":of})
    desigdf=pd.DataFrame(desigrows)

    alloc.to_excel(FINAL_ALLOC_FILE,index=False)
    with pd.ExcelWriter(ALLOC_REPORT_FILE,engine="openpyxl") as w2:
        desigdf.to_excel(w2,sheet_name="Designation_Summary",index=False)
        sumdf.to_excel(w2,  sheet_name="Faculty_Summary",    index=False)
        slotdf.to_excel(w2, sheet_name="Slot_Verification",  index=False)
        alloc.to_excel(w2,  sheet_name="Full_Allocation",    index=False)

    tot=len(alloc); ab2=alloc["Allocated_By"]
    unmet=slotdf[~slotdf["Status"].str.startswith("✓")]; gaps=sumdf[sumdf["Gap"]>0]
    log(f"\n{'='*62}\n  RESULTS  [{method}]\n{'='*62}")
    log(f"  Total assignments       : {tot}")
    log(f"  ├─ Exact willingness    : {int((ab2=='Willingness-Exact').sum())}")
    log(f"  ├─ ACP offline→online   : {int((ab2=='Willingness-ACPOnline').sum())}")
    log(f"  ├─ Session flip FN↔AN   : {int((ab2=='Willingness-SessionFlip').sum())}")
    log(f"  ├─ Adjacent day ±1      : {int((ab2=='Willingness-±1Day').sum())}")
    log(f"  └─ Auto-assigned        : {int(ab2.isin(['Auto-Assigned','OR-Assigned','Gap-Fill']).sum())}")
    log(f"\n  Slot fulfilment : {len(slotdf)-len(unmet)}/{len(slotdf)}"
        +(" ✓ ALL MET" if len(unmet)==0 else f"  ⚠ {len(unmet)} unmet"))
    log(f"  Faculty targets : {len(sumdf)-len(gaps)}/{len(sumdf)}"
        +(" ✓ ALL MET" if len(gaps)==0 else f"  ⚠ {len(gaps)} short"))
    acp=sumdf[sumdf["Designation"]=="ACP"]
    log(f"  ACP (≥1 online + ≥1 offline): {len(acp[(acp['Online']>=1)&(acp['Offline']>=1)])}/{len(acp)}")
    log(f"\n  Saved: {FINAL_ALLOC_FILE}  |  {ALLOC_REPORT_FILE}")
    return alloc, sumdf, slotdf, desigdf


# ═══════════════════════════════════════════════════════════════ #
#                   SESSION STATE DEFAULTS                       #
# ═══════════════════════════════════════════════════════════════ #
for k,v in {"logged_in":False,"admin_authenticated":False,
            "panel_mode":"User View","user_panel_mode":"Willingness",
            "selected_faculty":"","selected_slots":[],
            "confirm_delete":False,
            "pending_submissions":pd.DataFrame(columns=["Faculty","Date","Session"])}.items():
    if k not in st.session_state: st.session_state[k]=v


# ═══════════════════════════════════════════════════════════════ #
#                         LOGIN                                  #
# ═══════════════════════════════════════════════════════════════ #
if not st.session_state.logged_in:
    render_header(logo=True)
    _,c2,_=st.columns([1,2,1])
    with c2:
        st.markdown('<div class="card"><div class="card-title">🔒 Faculty Login</div>'
                    '<p class="card-sub">Enter your credentials to access the portal.</p></div>',
                    unsafe_allow_html=True)
        un=st.text_input("Username"); pw=st.text_input("Password",type="password")
        if st.button("Sign In",use_container_width=True):
            if un=="SASTRA" and pw=="SASTRA":
                st.session_state.logged_in=True; st.rerun()
            else: st.error("Invalid credentials.")
    st.markdown("---")
    st.caption("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()


# ═══════════════════════════════════════════════════════════════ #
#                      LOAD CORE DATA                            #
# ═══════════════════════════════════════════════════════════════ #
if not os.path.exists(FACULTY_FILE):
    st.error(f"**{FACULTY_FILE}** not found. Upload it to your GitHub repo."); st.stop()

fac_df=pd.read_excel(FACULTY_FILE); fac_df.columns=fac_df.columns.str.strip()
fac_df.rename(columns={fac_df.columns[0]:"Name",fac_df.columns[1]:"Designation"},inplace=True)
fac_df["Clean"]=fac_df["Name"].apply(clean)

offline_df, online_df = load_slots(OFFLINE_FILE, ONLINE_FILE)


# ═══════════════════════════════════════════════════════════════ #
#                  HEADER + NOTICE BANNER                        #
# ═══════════════════════════════════════════════════════════════ #
render_header(logo=False)
st.markdown("<div class='blink'><strong>Note:</strong> The University Examination Committee "
            "sincerely appreciates your cooperation. Every effort will be made to accommodate "
            "your willingness while adhering to institutional requirements. Final duty allocation "
            "is carried out using AI-assisted MILP optimization.</div>", unsafe_allow_html=True)
st.markdown("")

panel_mode=st.radio("Main Menu",["User View","Admin View"],horizontal=True,key="panel_mode")


# ═══════════════════════════════════════════════════════════════ #
#                        ADMIN VIEW                              #
# ═══════════════════════════════════════════════════════════════ #
if panel_mode=="Admin View":
    st.markdown('<div class="card"><div class="card-title">🔒 Admin View</div>'
                '<p class="card-sub">Protected. Enter admin password to continue.</p></div>',
                unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        ap=st.text_input("Admin Password",type="password",key="admpw")
        if st.button("Unlock",use_container_width=True):
            if ap=="sathya": st.session_state.admin_authenticated=True; st.rerun()
            else: st.error("Incorrect password.")
    else:
        st.success("✅ Admin unlocked.")
        t1,t2,t3=st.tabs(["📋 Willingness Records","🤖 Run Optimizer","📊 View Results"])

        with t1:
            st.markdown("### Willingness Records")
            st.markdown("Shows data from **`Willingness.xlsx`** (GitHub) + new in-session submissions.")
            w_all=get_all_willingness()
            if w_all.empty:
                st.info("No willingness data found.\n\n"
                        "**Workflow:** Faculty submit via User View → "
                        "Download CSV below → Save as Willingness.xlsx → "
                        "Upload to GitHub → Run Optimizer.")
            else:
                vdf=w_all.drop(columns=["FacultyClean"],errors="ignore").reset_index(drop=True)
                if "Sl.No" not in vdf.columns: vdf.insert(0,"Sl.No",vdf.index+1)
                sub_cnt=vdf["Faculty"].nunique() if "Faculty" in vdf.columns else 0
                c1,c2,c3=st.columns(3)
                c1.metric("Faculty Submitted",  sub_cnt)
                c2.metric("Not Yet Submitted",  len(fac_df)-sub_cnt)
                c3.metric("Total Rows",          len(vdf))
                st.dataframe(vdf,use_container_width=True,hide_index=True)
                st.download_button(
                    "⬇ Download Willingness CSV",
                    data=vdf[["Faculty","Date","Session"]].to_csv(index=False).encode("utf-8"),
                    file_name="Willingness.csv", mime="text/csv",
                    help="Download → open in Excel → Save As Willingness.xlsx → upload to GitHub")
                st.caption("📌 Download CSV → save as **Willingness.xlsx** → "
                           "upload to GitHub repo → run optimizer.")
            st.markdown("---")
            st.markdown("#### ⚠ Clear In-Session Submissions")
            st.checkbox("Confirm clearing all in-session submissions",key="confirm_delete")
            if st.button("Clear Session Submissions",type="primary"):
                if st.session_state.confirm_delete:
                    st.session_state.pending_submissions=pd.DataFrame(columns=["Faculty","Date","Session"])
                    st.success("Cleared."); st.session_state.confirm_delete=False; st.rerun()
                else: st.error("Tick the confirmation checkbox first.")

        with t2:
            st.markdown("### Run Allocation Optimizer")
            def fstat(f): return "✅ Found" if os.path.exists(f) else "❌ Missing"
            wstat = "✅ Found" if os.path.exists(WILLINGNESS_FILE) else "⚠ Not found (all faculty auto-assigned)"
            st.markdown(f"""
| File | Purpose | Status |
|---|---|---|
| `Faculty_Master.xlsx` | Faculty list + designations | {fstat(FACULTY_FILE)} |
| `Offline_Duty.xlsx` | Offline exam slots | {fstat(OFFLINE_FILE)} |
| `Online_Duty.xlsx` | Online exam slots | {fstat(ONLINE_FILE)} |
| `Willingness.xlsx` | Faculty willingness submissions | {wstat} |
""")
            wn=get_all_willingness()
            sc2=wn["Faculty"].nunique() if not wn.empty and "Faculty" in wn.columns else 0
            c1,c2,c3=st.columns(3)
            c1.metric("Total Faculty",         len(fac_df))
            c2.metric("Willingness Submitted", f"{sc2}/{len(fac_df)}")
            c3.metric("Willingness Rows",       len(wn))
            if not os.path.exists(FACULTY_FILE) or not os.path.exists(OFFLINE_FILE):
                st.error("Faculty_Master.xlsx and Offline_Duty.xlsx are required.")
            elif not SCIPY_OK:
                st.error("scipy not installed. Add `scipy` to requirements.txt and redeploy.")
            else:
                if not os.path.exists(WILLINGNESS_FILE):
                    st.warning("Willingness.xlsx not found — all faculty will be auto-assigned. "
                               "Upload the file to GitHub to use submitted preferences.")
                if st.button("▶ Run Optimizer",type="primary",use_container_width=True):
                    lb2=st.empty()
                    with st.spinner("Running MILP optimization — may take a few minutes..."):
                        try:
                            run_optimizer(lb2)
                            st.success("✅ Optimization complete! See View Results tab.")
                            st.balloons()
                        except Exception as e: st.error(f"Optimizer error: {e}")

        with t3:
            st.markdown("### Allocation Results")
            if not os.path.exists(FINAL_ALLOC_FILE):
                st.info("No results yet. Run the optimizer first.")
            else:
                av=pd.read_excel(FINAL_ALLOC_FILE); rep={}
                if os.path.exists(ALLOC_REPORT_FILE):
                    xl2=pd.ExcelFile(ALLOC_REPORT_FILE)
                    for sh in xl2.sheet_names: rep[sh]=xl2.parse(sh)
                tot2=len(av)
                if tot2>0 and "Allocated_By" in av.columns:
                    ab3=av["Allocated_By"]; aut=int(ab3.isin(["Auto-Assigned","OR-Assigned","Gap-Fill"]).sum())
                    c1,c2,c3,c4=st.columns(4)
                    c1.metric("Total Assignments",int(tot2))
                    c2.metric("Exact Willingness",int((ab3=="Willingness-Exact").sum()))
                    c3.metric("Auto-Assigned",    aut)
                    c4.metric("Match %",          f"{(tot2-aut)/tot2*100:.1f}%")
                for sh_name,label in [("Designation_Summary","Designation Summary"),
                                       ("Slot_Verification","Slot Verification"),
                                       ("Faculty_Summary","Faculty Summary")]:
                    if sh_name in rep:
                        st.markdown(f"#### {label}")
                        if sh_name=="Slot_Verification" and "Status" in rep[sh_name].columns:
                            um=rep[sh_name][~rep[sh_name]["Status"].str.startswith("✓")]
                            st.metric("Slots Fulfilled",f"{len(rep[sh_name])-len(um)}/{len(rep[sh_name])}",
                                      delta="All Met ✓" if len(um)==0 else f"{len(um)} unmet ⚠")
                        st.dataframe(rep[sh_name],use_container_width=True,hide_index=True)
                st.markdown("#### Full Allocation Table")
                st.dataframe(av,use_container_width=True,hide_index=True)
                col1,col2=st.columns(2)
                with col1:
                    with open(FINAL_ALLOC_FILE,"rb") as fh:
                        st.download_button("⬇ Final_Allocation.xlsx",data=fh.read(),
                                           file_name="Final_Allocation.xlsx",
                                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                with col2:
                    with open(ALLOC_REPORT_FILE,"rb") as fh:
                        st.download_button("⬇ Allocation_Report.xlsx",data=fh.read(),
                                           file_name="Allocation_Report.xlsx",
                                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        st.markdown("")
        if st.button("🔒 Lock Admin View",use_container_width=True):
            st.session_state.admin_authenticated=False; st.rerun()

    st.markdown("---")
    st.caption("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()


# ═══════════════════════════════════════════════════════════════ #
#                        USER VIEW                               #
# ═══════════════════════════════════════════════════════════════ #
user_mode=st.radio("User View",["Willingness","Allotment"],horizontal=True,key="user_panel_mode")


# ─── ALLOTMENT VIEW ──────────────────────────────────────────── #
if user_mode=="Allotment":
    st.markdown("### My Allotment Details")
    fnames=fac_df["Name"].dropna().drop_duplicates().tolist()
    sn=st.selectbox("Select Your Name",fnames,key="aname"); sc=clean(sn)
    frd=fac_df[fac_df["Clean"]==sc]
    vd,qd=[],[]
    if not frd.empty:
        fr2=frd.iloc[0]
        vd=[f"{fmt_day(d.strftime('%d-%m-%Y'))} - Full Day" for d in valuation_dates_for(fr2)]
        qd=[fmt_day(d) for d in qp_dates_for(fr2)]
    wd2=load_willingness(); wdisp,wpairs=[],set()
    if not wd2.empty:
        wm=fac_mask(wd2,sc); wr=wd2[wm]
        if not wr.empty and {"Date","Session"}.issubset(wr.columns):
            for d2,s2 in zip(wr["Date"],wr["Session"]):
                wdisp.append(f"{fmt_day(d2)} - {str(s2).upper()}")
                nd=pd.to_datetime(d2,dayfirst=True,errors="coerce")
                if pd.notna(nd): wpairs.add((nd.date(),str(s2).upper()))
    adf=pd.read_excel(FINAL_ALLOC_FILE) if os.path.exists(FINAL_ALLOC_FILE) else pd.DataFrame()
    idisp,ipairs=[],set()
    if not adf.empty:
        am=fac_mask(adf,sc); ar=adf[am]
        if not ar.empty and {"Date","Session"}.issubset(ar.columns):
            for d2,s2 in zip(ar["Date"],ar["Session"]):
                idisp.append(f"{fmt_day(d2)} - {str(s2).upper()}")
                nd=pd.to_datetime(d2,dayfirst=True,errors="coerce")
                if pd.notna(nd): ipairs.add((nd.date(),str(s2).upper()))
    acc="Not available"
    if wpairs:
        m2=len(wpairs&ipairs); acc=f"{m2/len(wpairs)*100:.1f}% ({m2}/{len(wpairs)})"
    c1,c2=st.columns(2)
    with c1:
        st.markdown('<div class="panel"><div class="sec-title">1) Willingness Options Submitted</div></div>',unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details":wdisp or ["Not submitted"]}),use_container_width=True,hide_index=True)
        st.markdown('<div class="panel"><div class="sec-title">3) Invigilation Dates (Final Allotment)</div></div>',unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details":idisp or ["Not allotted yet"]}),use_container_width=True,hide_index=True)
    with c2:
        st.markdown('<div class="panel"><div class="sec-title">2) Valuation Dates (Full Day)</div></div>',unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details":vd or ["Not available"]}),use_container_width=True,hide_index=True)
        st.markdown('<div class="panel"><div class="sec-title">4) QP Feedback Dates</div></div>',unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details":qd or ["Not available"]}),use_container_width=True,hide_index=True)
    st.info(f"📊 Willingness accommodated: **{acc}**")
    msg=build_msg(sn,wdisp,vd,idisp,qd,acc)
    st.markdown('<div class="panel"><div class="sec-title">📲 Share via WhatsApp</div></div>',unsafe_allow_html=True)
    wph=st.text_input("WhatsApp Number (with country code)",placeholder="+919876543210")
    if st.button("Generate WhatsApp Link",use_container_width=True):
        if not wph.strip(): st.warning("Enter a number.")
        else:
            lnk=wa_link(wph.strip(),msg)
            st.markdown(f'<a href="{lnk}" target="_blank" style="display:inline-block;'
                        f'background:#25D366;color:white;padding:10px 22px;border-radius:10px;'
                        f'font-weight:700;text-decoration:none;">📲 Open WhatsApp & Send</a>',
                        unsafe_allow_html=True)
    with st.expander("Preview Message"): st.code(msg,language="text")
    st.markdown("---")
    st.caption("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()


# ─── WILLINGNESS SUBMISSION ───────────────────────────────────── #
fnames2=fac_df["Name"].dropna().drop_duplicates().tolist()
sel_name=st.selectbox("Select Your Name",fnames2)
sel_clean=clean(sel_name)
fmatch=fac_df[fac_df["Clean"]==sel_clean]
if fmatch.empty: st.error("Faculty not found. Contact admin."); st.stop()

frow2    = fmatch.iloc[0]
desig2   = str(frow2["Designation"]).strip().upper()
req_cnt  = DUTY_STRUCTURE.get(desig2, 0)
val_d2   = valuation_dates_for(frow2)
val_s2   = set(val_d2)

if req_cnt==0: st.warning(f"Designation '{desig2}' not recognised. Contact admin.")

sopts = online_df.copy() if desig2=="P" else offline_df.copy()
slabel= "Choose Online Date" if desig2=="P" else "Choose Offline Date"
sopts["Date"]    = pd.to_datetime(sopts["Date"], errors="coerce")
sopts["DateOnly"]= sopts["Date"].dt.date
valid_d = sorted([d for d in sopts["DateOnly"].dropna().unique() if d not in val_s2])

if st.session_state.selected_faculty != sel_clean:
    st.session_state.selected_faculty = sel_clean
    st.session_state.selected_slots   = []
    st.session_state["picked_date"]   = valid_d[0] if valid_d else None
if "picked_date" not in st.session_state:
    st.session_state["picked_date"] = valid_d[0] if valid_d else None

left,right=st.columns([1,1.4])
with left:
    st.subheader("Willingness Submission")
    st.write(f"**Designation:** {desig2}")
    st.write(f"**Options to Select:** {req_cnt}")
    if desig2=="ACP":
        st.info("ACP faculty will receive one Online and one Offline duty. "
                "Please select all available dates from the Offline calendar. "
                "Online duty will be assigned automatically from your submitted dates.")
    if not valid_d:
        st.warning("No dates available for selection.")
    else:
        picked=st.selectbox(slabel,valid_d,key="picked_date",
                            format_func=lambda d:d.strftime("%d-%m-%Y (%A)"))
        avail=set(sopts[sopts["DateOnly"]==picked]["Session"].dropna().astype(str).str.upper())
        b1,b2=st.columns(2)
        with b1: add_fn=st.button("➕ Add FN",use_container_width=True,
                                   disabled=("FN" not in avail) or (len(st.session_state.selected_slots)>=req_cnt))
        with b2: add_an=st.button("➕ Add AN",use_container_width=True,
                                   disabled=("AN" not in avail) or (len(st.session_state.selected_slots)>=req_cnt))
        def add_slot(sess):
            exist={s["Date"] for s in st.session_state.selected_slots}
            sl2={"Date":picked,"Session":sess}
            if picked in val_s2:             st.warning("Valuation date — cannot select.")
            elif picked in exist:            st.warning("Both FN and AN on same date not allowed.")
            elif len(st.session_state.selected_slots)>=req_cnt: st.warning("Count reached.")
            elif sl2 in st.session_state.selected_slots: st.warning("Already selected.")
            else: st.session_state.selected_slots.append(sl2)
        if add_fn: add_slot("FN")
        if add_an: add_slot("AN")

    st.session_state.selected_slots=st.session_state.selected_slots[:req_cnt]
    st.write(f"**Selected:** {len(st.session_state.selected_slots)} / {req_cnt}")
    sdf=pd.DataFrame(st.session_state.selected_slots)
    if not sdf.empty:
        sdf=sdf.sort_values(["Date","Session"]).reset_index(drop=True)
        if "Sl.No" not in sdf.columns: sdf.insert(0,"Sl.No",sdf.index+1)
        sdf["Day"]=pd.to_datetime(sdf["Date"]).dt.day_name()
        sdf["Date"]=pd.to_datetime(sdf["Date"]).dt.strftime("%d-%m-%Y")
        st.dataframe(sdf[["Sl.No","Date","Day","Session"]],use_container_width=True,hide_index=True)
        rm=st.selectbox("Sl.No to remove",options=sdf["Sl.No"].tolist())
        if st.button("🗑 Remove Row",use_container_width=True):
            tgt=sdf[sdf["Sl.No"]==rm].iloc[0]
            td=pd.to_datetime(tgt["Date"],dayfirst=True).date(); ts=tgt["Session"]
            st.session_state.selected_slots=[s for s in st.session_state.selected_slots
                                              if not (s["Date"]==td and s["Session"]==ts)]
            st.rerun()

    wl2=load_willingness()
    already=(sel_clean in wl2["FacultyClean"].tolist()
             if not wl2.empty and "FacultyClean" in wl2.columns else False)
    pend=st.session_state.get("pending_submissions",pd.DataFrame(columns=["Faculty","Date","Session"]))
    if not pend.empty and "Faculty" in pend.columns:
        already=already or (sel_name in pend["Faculty"].tolist())

    st.markdown("### Submit Willingness")
    rem2=max(req_cnt-len(st.session_state.selected_slots),0)
    if already:       st.warning("⚠ You have already submitted your willingness.")
    elif rem2==0 and req_cnt>0: st.success(f"✅ All {req_cnt} options selected. Ready to submit.")
    else:             st.info(f"Select {rem2} more option(s) to enable submission.")

    if st.button("✅ Submit Willingness",
                 disabled=already or len(st.session_state.selected_slots)!=req_cnt,
                 use_container_width=True):
        save_submission(sel_name, st.session_state.selected_slots)
        st.session_state.selected_slots=[]
        st.toast("Willingness submitted successfully! ✅",icon="✅")
        st.success("Thank you for submitting. The final duty allocation will be carried out "
                   "using MILP optimization. Check this portal for allotment updates.")

with right:
    if desig2=="P": render_calendar(online_df, val_s2, "Online Duty Calendar")
    else:           render_calendar(offline_df,val_s2, "Offline Duty Calendar")

st.markdown("---")
st.caption("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
