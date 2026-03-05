"""
SASTRA SoME End Semester Examination Duty Portal
=================================================
Single-file Streamlit app combining:
  1) Willingness Collection (Faculty View)
  2) Admin View (willingness management)
  3) AI Allotment (MILP via SciPy HiGHS — same logic as v4 optimizer)
  4) Allotment View (per-faculty result + WhatsApp share)

Required files in the same directory:
  Faculty_with_initials.xlsx   — Name, Initials columns (ordered by designation)
  IG_Willingness.xlsx          — Offline slots then Online slots (exam schedule)
  sastra_logo.png              — (optional) logo image

Auto-created / written by app:
  Willingness.xlsx             — submitted willingness rows
  Final_Allocation.xlsx        — MILP allotment output
  Allocation_Report.xlsx       — designation / slot / faculty summaries
"""

import os, datetime, warnings, io, calendar as calmod, urllib.parse
import numpy as np
import pandas as pd
import streamlit as st
import altair as alt
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import csc_matrix
from collections import defaultdict

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────── #
#  FILE PATHS
# ─────────────────────────────────────────────────────────────────── #
FACULTY_FILE     = "Faculty_with_initials.xlsx"
IG_FILE          = "IG_Willingness.xlsx"
WILLINGNESS_FILE = "Willingness.xlsx"
FINAL_ALLOC_FILE = "Final_Allocation.xlsx"
REPORT_FILE      = "Allocation_Report.xlsx"
LOGO_FILE        = "sastra_logo.png"

# ─────────────────────────────────────────────────────────────────── #
#  DESIGNATION RULES  (mirror of v4 optimizer)
# ─────────────────────────────────────────────────────────────────── #
DESIG_RULES = {
    "P":   (1, 1, ["Online"]),
    "ACP": (2, 3, ["Online", "Offline"]),
    "SAP": (3, 3, ["Offline"]),
    "AP3": (3, 3, ["Offline"]),
    "AP2": (3, 3, ["Offline"]),
    "TA":  (3, 3, ["Offline"]),
    "RA":  (4, 4, ["Offline"]),
}
DESIG_ORDER = [("P",7),("ACP",13),("SAP",13),("AP3",13),("AP2",3),("TA",19),("RA",2)]

# Willingness UI: how many options each designation must submit
DESIG_UI_COUNT = {
    "P":   3,
    "ACP": 5,
    "SAP": 7,
    "AP3": 7,
    "AP2": 7,
    "TA":  9,
    "RA":  9,
}

# Willingness weight tiers
W_EXACT      = 100
W_FLIP       = 70
W_ADJ        = 40
W_ACP_ONLINE = 60
W_NON_SUB    = 5
PENALTY      = 30

# ─────────────────────────────────────────────────────────────────── #
#  PAGE CONFIG & GLOBAL CSS
# ─────────────────────────────────────────────────────────────────── #
st.set_page_config(page_title="SASTRA Duty Portal", layout="wide")
st.markdown("""
<style>
.stApp { background: #f4f7fb; }
.main .block-container { max-width: 1180px; padding-top: 1.2rem; padding-bottom: 1.2rem; }
.secure-card {
    background: linear-gradient(180deg,#ffffff 0%,#f8fafc 100%);
    border: 1px solid #dbe3ef; border-radius: 14px;
    padding: 16px 18px; box-shadow: 0 10px 24px rgba(15,23,42,0.08); margin-bottom: 12px;
}
.panel-card {
    background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px;
    padding: 14px 16px; box-shadow: 0 8px 20px rgba(15,23,42,0.06); margin-bottom: 10px;
}
.secure-title { font-size: 1.08rem; font-weight: 700; color: #0f172a; margin-bottom: 0.2rem; }
.secure-sub   { font-size: 0.93rem; color: #334155; margin-bottom: 0; }
.section-title{ font-size: 1rem; font-weight: 700; color: #0b3a67; margin-bottom: 0.35rem; }
.stButton>button        { border-radius: 10px; border: 1px solid #cbd5e1; font-weight: 600; }
.stDownloadButton>button{ border-radius: 10px; font-weight: 600; }
[data-testid="stRadio"] label p { font-weight: 600; }
.blink-notice {
    font-weight: 700; color: #800000; padding: 10px 12px;
    border: 2px solid #800000; background: #fffaf5; border-radius: 6px;
    animation: blinkPulse 2.4s ease-in-out infinite;
}
@keyframes blinkPulse { 0%{opacity:1} 50%{opacity:.35} 100%{opacity:1} }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────── #
#  HELPERS
# ─────────────────────────────────────────────────────────────────── #
def clean(x):
    return str(x).strip().lower()

def normalize_session(v):
    t = str(v).strip().upper()
    if t in {"FN","FORENOON","MORNING","AM"}: return "FN"
    if t in {"AN","AFTERNOON","EVENING","PM"}: return "AN"
    return t

def format_with_day(date_text):
    dt = pd.to_datetime(date_text, dayfirst=True, errors="coerce")
    if pd.isna(dt): return str(date_text).strip()
    return f"{dt.strftime('%d-%m-%Y')} ({dt.strftime('%A')})"

def get_whatsapp_link(phone, message):
    clean_phone = str(phone).strip().replace("+","").replace(" ","").replace("-","")
    return f"https://wa.me/{clean_phone}?text={urllib.parse.quote(message)}"

# ─────────────────────────────────────────────────────────────────── #
#  DATA LOADERS
# ─────────────────────────────────────────────────────────────────── #
@st.cache_data(ttl=30)
def load_faculty_df():
    if not os.path.exists(FACULTY_FILE):
        st.error(f"{FACULTY_FILE} not found."); st.stop()
    df = pd.read_excel(FACULTY_FILE)
    df.columns = ["Name","Initials"] + list(df.columns[2:])
    df["Name"] = df["Name"].astype(str).str.strip()
    return df

@st.cache_data(ttl=30)
def load_ig_slots():
    if not os.path.exists(IG_FILE):
        st.error(f"{IG_FILE} not found."); st.stop()
    raw = pd.read_excel(IG_FILE, header=None)

    def parse_section(start, end, duty_type):
        slots = []
        for i in range(start, end):
            row = raw.iloc[i]
            d, sess, req = row.iloc[0], row.iloc[1], row.iloc[2]
            if pd.isna(d) or str(sess).strip().upper() not in ("FN","AN"): continue
            try:    date = pd.to_datetime(d).date()
            except: continue
            try:    required = max(int(float(req)), 0)
            except: required = 1
            slots.append({"date":date,"session":str(sess).strip().upper(),
                          "required":required,"type":duty_type})
        return slots

    online_header_row = None
    for i in range(len(raw)):
        cell = str(raw.iloc[i,0])
        if "GCR Online" in cell or "online exams" in cell.lower():
            online_header_row = i; break

    offline_end  = online_header_row - 1 if online_header_row else len(raw)
    online_start = online_header_row + 2 if online_header_row else None

    slots_offline = parse_section(1, offline_end, "Offline")
    slots_online  = parse_section(online_start, len(raw), "Online") if online_start else []
    return slots_offline, slots_online

def load_willingness():
    if os.path.exists(WILLINGNESS_FILE):
        df = pd.read_excel(WILLINGNESS_FILE)
        if "Faculty" not in df.columns: df["Faculty"] = ""
        df["FacultyClean"] = df["Faculty"].apply(clean)
        return df
    return pd.DataFrame(columns=["Faculty","Date","Session","FacultyClean"])

def save_willingness(df):
    df.drop(columns=["FacultyClean"], errors="ignore").to_excel(WILLINGNESS_FILE, index=False)

def load_final_allotment():
    if os.path.exists(FINAL_ALLOC_FILE):
        try:   return pd.read_excel(FINAL_ALLOC_FILE)
        except: pass
    return pd.DataFrame()

def faculty_match_mask(df, selected_clean):
    if df.empty: return pd.Series([], dtype=bool)
    name_cols = [c for c in df.columns if "name" in str(c).lower() or "faculty" in str(c).lower()]
    if not name_cols: return pd.Series([False]*len(df), index=df.index)
    mask = pd.Series([False]*len(df), index=df.index)
    for col in name_cols:
        mask = mask | (df[col].astype(str).apply(clean) == selected_clean)
    return mask

def slots_to_duty_df(slots, dtype):
    rows = [{"Date": pd.Timestamp(s["date"]), "Session": s["session"]} for s in slots if s["type"]==dtype]
    return pd.DataFrame(rows) if rows else pd.DataFrame(columns=["Date","Session"])

# ─────────────────────────────────────────────────────────────────── #
#  CALENDAR HEAT MAP
# ─────────────────────────────────────────────────────────────────── #
def demand_category(r):
    if r < 3:  return "Low (<3)"
    if r <= 7: return "Medium (3-7)"
    return "High (>7)"

def build_month_calendar_frame(duty_df, valuation_dates, year, month):
    session_demand = duty_df.groupby(["Date","Session"], as_index=False)["Required"].sum() \
        if "Required" in duty_df.columns else \
        duty_df.groupby(["Date","Session"]).size().reset_index(name="Required")
    demand_map = {(d.date(), str(s).upper()): int(r)
                  for d,s,r in zip(session_demand["Date"],session_demand["Session"],session_demand["Required"])}
    month_start = pd.Timestamp(year=year, month=month, day=1)
    month_end   = month_start + pd.offsets.MonthEnd(0)
    first_weekday = month_start.weekday()
    wlabels = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    rows = []
    for dt in pd.date_range(month_start, month_end, freq="D"):
        week_no  = ((dt.day + first_weekday - 1) // 7) + 1
        date_only = dt.date()
        for sess in ["FN","AN"]:
            req = demand_map.get((date_only, sess), 0)
            if date_only in valuation_dates: cat = "Valuation Locked"
            elif req == 0:                   cat = "No Duty"
            else:                            cat = demand_category(req)
            rows.append({"Date":dt,"Week":week_no,"Weekday":wlabels[dt.weekday()],
                         "DayNum":dt.day,"Session":sess,"Required":req,"Category":cat,
                         "DateLabel":dt.strftime("%d-%m-%Y")})
    return pd.DataFrame(rows)

def render_month_calendars(duty_df, valuation_set, title):
    st.markdown(f"#### {title}")
    if duty_df.empty or "Date" not in duty_df.columns:
        st.info("No schedule data available."); return
    months = sorted({(d.year, d.month) for d in duty_df["Date"]})
    color_scale = alt.Scale(
        domain=["No Duty","Low (<3)","Medium (3-7)","High (>7)","Valuation Locked"],
        range=["#ececec","#2ca02c","#f1c40f","#d62728","#ff69b4"])
    st.markdown("**Heat Map:** ⬜ No Duty  🟩 Low  🟨 Medium  🟥 High  🩷 Valuation")
    for year, month in months:
        frame = build_month_calendar_frame(duty_df, valuation_set, year, month)
        st.markdown(f"**{calmod.month_name[month]} {year}**")
        base = alt.Chart(frame).encode(
            x=alt.X("Weekday:N", sort=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"], title=""),
            xOffset=alt.XOffset("Session:N", sort=["FN","AN"]),
            y=alt.Y("Week:O", sort="ascending", title=""),
            tooltip=[alt.Tooltip("DateLabel:N",title="Date"),
                     alt.Tooltip("Session:N",title="Session"),
                     alt.Tooltip("Required:Q",title="Demand"),
                     alt.Tooltip("Category:N",title="Category")])
        rect = base.mark_rect(stroke="white").encode(
            color=alt.Color("Category:N", scale=color_scale,
                            legend=alt.Legend(title="Legend")))
        day_text = (alt.Chart(frame[frame["Session"]=="FN"])
                    .mark_text(color="black",fontSize=11,dy=-6)
                    .encode(x=alt.X("Weekday:N",sort=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]),
                            y=alt.Y("Week:O",sort="ascending"),
                            text=alt.Text("DayNum:Q")))
        st.altair_chart((rect+day_text).properties(height=230), use_container_width=True)
        st.caption("Left half = FN, Right half = AN per date.")

# ─────────────────────────────────────────────────────────────────── #
#  MILP ALLOTMENT ENGINE  (v4 logic)
# ─────────────────────────────────────────────────────────────────── #
def run_milp_allotment(all_faculty, fac_desig, csv_df, all_slots, submitted_faculty, non_submitted):
    N_FAC   = len(all_faculty)
    FAC_IDX = {n: i for i, n in enumerate(all_faculty)}
    N_SLOTS = len(all_slots)

    # ── Build expanded willingness ──────────────────────────────── #
    fac_expanded = defaultdict(dict)

    # Step 1 — exact CSV entries
    for _, row in csv_df.iterrows():
        name = row["Faculty"]
        if name not in FAC_IDX: continue
        date = pd.to_datetime(row["Date"], dayfirst=True).date()
        sess = str(row["Session"]).strip().upper()
        desig   = fac_desig.get(name,"TA")
        allowed = DESIG_RULES[desig][2]
        for dtype in allowed:
            key = (date,sess,dtype)
            fac_expanded[name][key] = max(fac_expanded[name].get(key,0), W_EXACT)
        if desig == "ACP":
            for s2 in ["FN","AN"]:
                ok = (date,s2,"Online")
                fac_expanded[name][ok] = max(fac_expanded[name].get(ok,0), W_ACP_ONLINE)

    # Step 2 — session flip
    for name in list(fac_expanded.keys()):
        for (date,sess,dtype), score in list(fac_expanded[name].items()):
            if score < W_FLIP: continue
            opp = "AN" if sess=="FN" else "FN"
            fk  = (date,opp,dtype)
            fac_expanded[name][fk] = max(fac_expanded[name].get(fk,0), W_FLIP)

    # Step 3 — ±1 day
    for name in list(fac_expanded.keys()):
        for (date,sess,dtype), score in list(fac_expanded[name].items()):
            if score < W_FLIP: continue
            for delta in [-1,+1]:
                adj_date = date + datetime.timedelta(days=delta)
                for adj_sess in ["FN","AN"]:
                    ak = (adj_date,adj_sess,dtype)
                    fac_expanded[name][ak] = max(fac_expanded[name].get(ak,0), W_ADJ)

    # Step 4 — non-submitted faculty
    for name in non_submitted:
        desig   = fac_desig.get(name,"TA")
        allowed = DESIG_RULES[desig][2]
        for slot in all_slots:
            if slot["type"] in allowed:
                key = (slot["date"],slot["session"],slot["type"])
                if key not in fac_expanded[name]:
                    fac_expanded[name][key] = W_NON_SUB

    # ── Build MILP ─────────────────────────────────────────────── #
    def var(f,s): return f*N_SLOTS+s
    N_VARS = N_FAC * N_SLOTS
    c  = np.zeros(N_VARS)
    lb = np.zeros(N_VARS)
    ub = np.ones(N_VARS)

    for f_idx, f_name in enumerate(all_faculty):
        desig   = fac_desig[f_name]
        allowed = DESIG_RULES[desig][2]
        has_sub = f_name in submitted_faculty
        for s_idx, slot in enumerate(all_slots):
            dtype = slot["type"]
            if dtype not in allowed:
                ub[var(f_idx,s_idx)] = 0.0; continue
            key   = (slot["date"],slot["session"],dtype)
            score = fac_expanded[f_name].get(key,0)
            if score > 0:
                c[var(f_idx,s_idx)] = -float(score)
            elif has_sub:
                c[var(f_idx,s_idx)] = float(PENALTY)

    rows_A, cols_A, data_A, b_lo, b_hi = [], [], [], [], []
    n_c = [0]
    def add(vids, coeffs, lo, hi):
        for vi,co in zip(vids,coeffs):
            rows_A.append(n_c[0]); cols_A.append(vi); data_A.append(float(co))
        b_lo.append(float(lo)); b_hi.append(float(hi)); n_c[0]+=1

    online_idxs  = [i for i,s in enumerate(all_slots) if s["type"]=="Online"]
    offline_idxs = [i for i,s in enumerate(all_slots) if s["type"]=="Offline"]

    # C1 — slot demand
    for s_idx, slot in enumerate(all_slots):
        add([var(f,s_idx) for f in range(N_FAC)], [1]*N_FAC,
            slot["required"], slot["required"])

    # C2 — faculty duty count
    for f_idx, f_name in enumerate(all_faculty):
        dr = DESIG_RULES[fac_desig[f_name]]
        add([var(f_idx,s) for s in range(N_SLOTS)], [1]*N_SLOTS, dr[0], dr[1])

    # C3 — no double-booking same date+type
    date_type_slots = defaultdict(list)
    for s_idx, slot in enumerate(all_slots):
        date_type_slots[(slot["date"],slot["type"])].append(s_idx)
    for f_idx in range(N_FAC):
        for (date,dtype), s_indices in date_type_slots.items():
            if len(s_indices) > 1:
                add([var(f_idx,si) for si in s_indices], [1]*len(s_indices), 0, 1)

    # C4 — P exactly 1 online
    for f_name in [n for n,d in fac_desig.items() if d=="P"]:
        f_idx = FAC_IDX[f_name]
        add([var(f_idx,si) for si in online_idxs], [1]*len(online_idxs), 1, 1)

    # C5 — ACP ≥1 online AND ≥1 offline
    for f_name in [n for n,d in fac_desig.items() if d=="ACP"]:
        f_idx = FAC_IDX[f_name]
        add([var(f_idx,si) for si in online_idxs],  [1]*len(online_idxs),  1, len(online_idxs))
        add([var(f_idx,si) for si in offline_idxs], [1]*len(offline_idxs), 1, len(offline_idxs))

    A = csc_matrix((data_A,(rows_A,cols_A)), shape=(n_c[0],N_VARS))
    constraints = LinearConstraint(A, b_lo, b_hi)
    bounds      = Bounds(lb=lb, ub=ub)
    integrality = np.ones(N_VARS)

    result = milp(c=c, constraints=constraints, integrality=integrality,
                  bounds=bounds, options={"disp":False,"time_limit":300})

    # ── Extract solution ──────────────────────────────────────── #
    assigned_slots = []
    if result.status in (0,1):
        x = np.round(result.x).astype(int)
        for f_idx, f_name in enumerate(all_faculty):
            for s_idx, slot in enumerate(all_slots):
                if x[var(f_idx,s_idx)] == 1:
                    key   = (slot["date"],slot["session"],slot["type"])
                    score = fac_expanded[f_name].get(key,0)
                    if f_name in non_submitted:          wb = "Auto-Assigned"
                    elif score >= W_EXACT:               wb = "Willingness-Exact"
                    elif score >= W_ACP_ONLINE:          wb = "Willingness-ACPOnline"
                    elif score >= W_FLIP:                wb = "Willingness-SessionFlip"
                    elif score >= W_ADJ:                 wb = "Willingness-±1Day"
                    elif score == W_NON_SUB:             wb = "Auto-Assigned"
                    else:                                wb = "OR-Assigned"
                    assigned_slots.append({"Name":f_name,"Date":slot["date"],
                                           "Session":slot["session"],"Type":slot["type"],
                                           "Allocated_By":wb})
        method = f"MILP Optimal (HiGHS) — status {result.message}"
    else:
        method = f"MILP FAILED: {result.message}"

    alloc_df = pd.DataFrame(assigned_slots) if assigned_slots else pd.DataFrame(
        columns=["Name","Date","Session","Type","Allocated_By"])
    if not alloc_df.empty:
        alloc_df["Date"] = pd.to_datetime(alloc_df["Date"]).dt.strftime("%d-%m-%Y")
        alloc_df = alloc_df.sort_values(["Date","Session","Name"]).reset_index(drop=True)
        alloc_df.insert(0,"Sl.No", alloc_df.index+1)

    return alloc_df, method, fac_expanded, result.status

def build_allocation_report(alloc_df, all_slots, all_faculty, fac_desig, submitted_faculty):
    # Summary per faculty
    summary_rows = []
    for name in all_faculty:
        desig  = fac_desig[name]
        dr     = DESIG_RULES[desig]
        rows_f = alloc_df[alloc_df["Name"]==name] if not alloc_df.empty else pd.DataFrame()
        assigned = len(rows_f)
        exact = len(rows_f[rows_f["Allocated_By"]=="Willingness-Exact"]) if not rows_f.empty else 0
        acpo  = len(rows_f[rows_f["Allocated_By"]=="Willingness-ACPOnline"]) if not rows_f.empty else 0
        flip  = len(rows_f[rows_f["Allocated_By"]=="Willingness-SessionFlip"]) if not rows_f.empty else 0
        adj   = len(rows_f[rows_f["Allocated_By"]=="Willingness-±1Day"]) if not rows_f.empty else 0
        auto  = len(rows_f[rows_f["Allocated_By"].isin(["Auto-Assigned","OR-Assigned"])]) if not rows_f.empty else 0
        on_cnt  = len(rows_f[rows_f["Type"]=="Online"]) if not rows_f.empty else 0
        off_cnt = len(rows_f[rows_f["Type"]=="Offline"]) if not rows_f.empty else 0
        summary_rows.append({"Name":name,"Designation":desig,
            "Submitted":"Yes" if name in submitted_faculty else "No",
            "Required_Duties":dr[0],"Assigned_Duties":assigned,
            "Willingness_Total":exact+acpo+flip+adj,
            "Exact_Match":exact,"ACP_Online":acpo,"Session_Flip":flip,"Adj_Day":adj,
            "Auto_Assigned":auto,"Online":on_cnt,"Offline":off_cnt,
            "Gap":max(dr[0]-assigned,0)})
    summary_df = pd.DataFrame(summary_rows)

    # Designation summary
    desig_rows = []
    for desig, cnt in DESIG_ORDER:
        sub = summary_df[summary_df["Designation"]==desig]
        on  = int(sub["Online"].sum()); off = int(sub["Offline"].sum())
        desig_rows.append({"Designation":desig,"Faculty_Count":cnt,
            "Duties_Per_Person":DESIG_RULES[desig][0],
            "Total_Required":DESIG_RULES[desig][0]*cnt,"Total_Assigned":on+off,
            "Willingness_Matched":int(sub["Willingness_Total"].sum()),
            "Auto_Assigned":int(sub["Auto_Assigned"].sum()),
            "Online":on,"Offline":off})
    desig_df = pd.DataFrame(desig_rows)

    # Slot verification
    slot_rows = []
    for slot in all_slots:
        ds = pd.Timestamp(slot["date"]).strftime("%d-%m-%Y")
        n_assigned = len(alloc_df[(alloc_df["Date"]==ds) &
                                  (alloc_df["Session"]==slot["session"]) &
                                  (alloc_df["Type"]==slot["type"])]) if not alloc_df.empty else 0
        slot_rows.append({"Date":ds,"Session":slot["session"],"Type":slot["type"],
            "Required":slot["required"],"Assigned":n_assigned,
            "Status":"✓" if n_assigned>=slot["required"] else f"✗ short {slot['required']-n_assigned}"})
    slot_df = pd.DataFrame(slot_rows)

    return summary_df, desig_df, slot_df

def save_allotment_files(alloc_df, summary_df, desig_df, slot_df):
    alloc_df.to_excel(FINAL_ALLOC_FILE, index=False)
    with pd.ExcelWriter(REPORT_FILE, engine="openpyxl") as w:
        desig_df.to_excel(w,   sheet_name="Designation_Summary", index=False)
        summary_df.to_excel(w, sheet_name="Faculty_Summary",     index=False)
        slot_df.to_excel(w,    sheet_name="Slot_Verification",   index=False)
        alloc_df.to_excel(w,   sheet_name="Full_Allocation",     index=False)

def df_to_xlsx_bytes(df):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False)
    return buf.getvalue()

# ─────────────────────────────────────────────────────────────────── #
#  SESSION STATE INIT
# ─────────────────────────────────────────────────────────────────── #
for key, val in [
    ("logged_in", False),
    ("admin_authenticated", False),
    ("panel_mode", "User View"),
    ("user_panel_mode", "Willingness"),
    ("selected_slots", []),
    ("selected_faculty", ""),
    ("acp_notice_shown_for", ""),
    ("milp_run_done", False),
    ("milp_alloc_df", pd.DataFrame()),
    ("milp_summary_df", pd.DataFrame()),
    ("milp_desig_df", pd.DataFrame()),
    ("milp_slot_df", pd.DataFrame()),
    ("milp_method", ""),
]:
    if key not in st.session_state:
        st.session_state[key] = val

# ─────────────────────────────────────────────────────────────────── #
#  BRANDING HEADER
# ─────────────────────────────────────────────────────────────────── #
def render_branding_header(show_logo=True):
    if show_logo and os.path.exists(LOGO_FILE):
        c1,c2,c3 = st.columns([2,1,2])
        with c2: st.image(LOGO_FILE, width=180)
    st.markdown("<h2 style='text-align:center;margin-bottom:0.25rem;'>"
                "SASTRA SoME End Semester Examination Duty Portal</h2>", unsafe_allow_html=True)
    st.markdown("<h4 style='text-align:center;margin-top:0;'>"
                "School of Mechanical Engineering</h4>", unsafe_allow_html=True)
    st.markdown("---")

# ─────────────────────────────────────────────────────────────────── #
#  LOGIN
# ─────────────────────────────────────────────────────────────────── #
if not st.session_state.logged_in:
    render_branding_header(show_logo=True)
    c1,c2,c3 = st.columns([1,2,1])
    with c2:
        st.markdown("""<div class="secure-card">
            <div class="secure-title">🔒 Faculty Login</div>
            <p class="secure-sub">Enter your authorized credentials to access the duty portal.</p>
        </div>""", unsafe_allow_html=True)
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Sign In", use_container_width=True):
            if username == "SASTRA" and password == "SASTRA":
                st.session_state.logged_in = True; st.rerun()
            else:
                st.error("Invalid credentials")
    st.markdown("---")
    st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()

# ─────────────────────────────────────────────────────────────────── #
#  MAIN PORTAL
# ─────────────────────────────────────────────────────────────────── #
render_branding_header(show_logo=False)

st.markdown("""<div class='blink-notice'><strong>Note:</strong> The University Examination Committee
sincerely appreciates your cooperation. Every effort will be made to accommodate your willingness,
while ensuring adherence to institutional requirements. The final duty allocation will be carried out
using AI-assisted optimization (HiGHS MILP).</div>""", unsafe_allow_html=True)
st.markdown("")

# Load shared data
fac_df = load_faculty_df()
ALL_FACULTY = [str(r["Name"]).strip() for _,r in fac_df.iterrows()]
fac_desig = {}
idx = 0
for desig, cnt in DESIG_ORDER:
    for _ in range(cnt):
        if idx < len(ALL_FACULTY):
            fac_desig[ALL_FACULTY[idx]] = desig; idx+=1

slots_offline, slots_online = load_ig_slots()
ALL_SLOTS = slots_offline + slots_online

# ── TOP NAV ──────────────────────────────────────────────────────── #
st.markdown('<div class="panel-card"><div class="section-title">Control Panel</div></div>',
            unsafe_allow_html=True)
panel_mode = st.radio("Main Menu", ["User View","Admin View"], horizontal=True, key="panel_mode")

# ═══════════════════════════════════════════════════════════════════ #
#  ADMIN VIEW
# ═══════════════════════════════════════════════════════════════════ #
if panel_mode == "Admin View":
    st.markdown("""<div class="secure-card">
        <div class="secure-title">🔒 Admin View (Secure Access)</div>
        <p class="secure-sub">Administrative functions are protected. Please authenticate.</p>
    </div>""", unsafe_allow_html=True)

    if not st.session_state.admin_authenticated:
        admin_pass = st.text_input("Admin Password", type="password", key="admin_password")
        if st.button("Unlock Admin View", use_container_width=True):
            if admin_pass == "sathya":
                st.session_state.admin_authenticated = True; st.success("Access granted."); st.rerun()
            else:
                st.error("Invalid admin password.")
        st.markdown("---")
        st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
        st.stop()

    st.success("Admin view unlocked")

    # ── Tabs ──────────────────────────────────────────────────────── #
    tab1, tab2, tab3 = st.tabs(["📋 Willingness Records", "⚙️ Run MILP Allotment", "📊 Allotment Results"])

    # ── Tab 1: Willingness Records ──────────────────────────────── #
    with tab1:
        st.markdown("### Submitted Willingness Records")
        will_df = load_willingness().drop(columns=["FacultyClean"], errors="ignore")
        submitted_set = set(will_df["Faculty"].dropna().str.strip().tolist()) if not will_df.empty else set()
        non_submitted_list = [n for n in ALL_FACULTY if n not in submitted_set]

        col1, col2, col3 = st.columns(3)
        col1.metric("Total Faculty", len(ALL_FACULTY))
        col2.metric("Submitted Willingness", len(submitted_set))
        col3.metric("Not Submitted (auto-assign)", len(non_submitted_list))

        if will_df.empty:
            st.info("No willingness submissions yet.")
        else:
            vw = will_df.copy().reset_index(drop=True)
            vw.insert(0, "Sl.No", vw.index+1)
            st.dataframe(vw, use_container_width=True, hide_index=True)
            csv_data = vw.to_csv(index=False).encode("utf-8")
            st.download_button("⬇ Download Willingness CSV", data=csv_data,
                               file_name="Willingness_Admin_View.csv", mime="text/csv")

        if non_submitted_list:
            with st.expander(f"Non-submitted faculty ({len(non_submitted_list)})"):
                for n in non_submitted_list:
                    st.write(f"• {n}  [{fac_desig.get(n,'?')}]")

        st.markdown("#### Delete All Willingness")
        confirm_del = st.checkbox("I confirm deletion of all submitted willingness records", key="confirm_del")
        if st.button("🗑 Delete All Willingness", type="primary"):
            if confirm_del:
                pd.DataFrame(columns=["Faculty","Date","Session"]).to_excel(WILLINGNESS_FILE, index=False)
                st.success("All willingness records deleted."); st.rerun()
            else:
                st.error("Please confirm deletion first.")

    # ── Tab 2: Run MILP ─────────────────────────────────────────── #
    with tab2:
        st.markdown("### AI-Assisted MILP Allotment (HiGHS Optimizer)")

        will_df2  = load_willingness()
        sub_set2  = set(will_df2["Faculty"].dropna().str.strip().tolist()) if not will_df2.empty else set()
        non_sub2  = [n for n in ALL_FACULTY if n not in sub_set2]

        st.write(f"**Slots:** {len(ALL_SLOTS)} ({len(slots_offline)} offline + {len(slots_online)} online)")
        st.write(f"**Total assignments needed:** {sum(s['required'] for s in ALL_SLOTS)}")
        st.write(f"**Submitted faculty:** {len(sub_set2)}  |  **Non-submitted (auto-assign):** {len(non_sub2)}")
        st.warning("Running the MILP can take 1–5 minutes depending on problem size. Do not close the page.")

        if st.button("🚀 Run MILP Allotment Now", type="primary", use_container_width=True):
            csv_for_milp = will_df2.rename(columns={"Faculty":"Faculty","Date":"Date","Session":"Session"})
            if "FacultyClean" in csv_for_milp.columns:
                csv_for_milp = csv_for_milp.drop(columns=["FacultyClean"])

            with st.spinner("Solving MILP — please wait..."):
                alloc_df, method, fac_exp, status = run_milp_allotment(
                    ALL_FACULTY, fac_desig, csv_for_milp, ALL_SLOTS, sub_set2, non_sub2)

            summary_df, desig_df, slot_df = build_allocation_report(
                alloc_df, ALL_SLOTS, ALL_FACULTY, fac_desig, sub_set2)

            st.session_state.milp_alloc_df   = alloc_df
            st.session_state.milp_summary_df = summary_df
            st.session_state.milp_desig_df   = desig_df
            st.session_state.milp_slot_df    = slot_df
            st.session_state.milp_method     = method
            st.session_state.milp_run_done   = True

            save_allotment_files(alloc_df, summary_df, desig_df, slot_df)

            if status in (0,1):
                st.success(f"✅ Allotment complete! Method: {method}")
            else:
                st.error(f"MILP failed: {method}. Check data.")

    # ── Tab 3: Allotment Results ─────────────────────────────────── #
    with tab3:
        st.markdown("### Allotment Results")
        if not st.session_state.milp_run_done and not os.path.exists(FINAL_ALLOC_FILE):
            st.info("Run the MILP allotment first (Tab 2).")
        else:
            # Load from session or disk
            if st.session_state.milp_run_done:
                alloc_df2   = st.session_state.milp_alloc_df
                summary_df2 = st.session_state.milp_summary_df
                desig_df2   = st.session_state.milp_desig_df
                slot_df2    = st.session_state.milp_slot_df
                method2     = st.session_state.milp_method
            else:
                alloc_df2 = load_final_allotment()
                will_df3  = load_willingness()
                sub_set3  = set(will_df3["Faculty"].dropna().str.strip().tolist()) if not will_df3.empty else set()
                summary_df2, desig_df2, slot_df2 = build_allocation_report(
                    alloc_df2, ALL_SLOTS, ALL_FACULTY, fac_desig, sub_set3)
                method2 = "Loaded from saved file"

            st.info(f"Method: {method2}")

            total   = len(alloc_df2)
            unmet   = slot_df2[~slot_df2["Status"].str.startswith("✓")] if not slot_df2.empty else pd.DataFrame()
            gaps    = summary_df2[summary_df2["Gap"]>0] if not summary_df2.empty else pd.DataFrame()

            m1,m2,m3,m4 = st.columns(4)
            m1.metric("Total Assignments", total)
            m2.metric("Slots Fulfilled", f"{len(slot_df2)-len(unmet)}/{len(slot_df2)}")
            m3.metric("Faculty Targets Met", f"{len(summary_df2)-len(gaps)}/{len(summary_df2)}")
            if total > 0:
                exact_n = len(alloc_df2[alloc_df2["Allocated_By"]=="Willingness-Exact"])
                m4.metric("Exact Willingness Match", f"{exact_n/total*100:.1f}%")

            sub_t1, sub_t2, sub_t3, sub_t4 = st.tabs(["Designation Summary","Slot Verification","Faculty Summary","Full Allocation"])
            with sub_t1:
                st.dataframe(desig_df2, use_container_width=True, hide_index=True)
            with sub_t2:
                st.dataframe(slot_df2, use_container_width=True, hide_index=True)
                if not unmet.empty:
                    st.error(f"⚠ {len(unmet)} slots unmet — may need to relax constraints or add faculty.")
            with sub_t3:
                st.dataframe(summary_df2, use_container_width=True, hide_index=True)
                if not gaps.empty:
                    st.warning(f"{len(gaps)} faculty below target duty count.")
            with sub_t4:
                st.dataframe(alloc_df2, use_container_width=True, hide_index=True)

            st.markdown("#### Download Reports")
            dl1, dl2 = st.columns(2)
            with dl1:
                st.download_button("⬇ Final_Allocation.xlsx",
                                   data=df_to_xlsx_bytes(alloc_df2),
                                   file_name="Final_Allocation.xlsx",
                                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            with dl2:
                if os.path.exists(REPORT_FILE):
                    with open(REPORT_FILE,"rb") as f:
                        st.download_button("⬇ Allocation_Report.xlsx", data=f.read(),
                                           file_name="Allocation_Report.xlsx",
                                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    if st.button("🔒 Lock Admin View", use_container_width=True):
        st.session_state.admin_authenticated = False; st.rerun()

    st.markdown("---")
    st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()

# ═══════════════════════════════════════════════════════════════════ #
#  USER VIEW
# ═══════════════════════════════════════════════════════════════════ #
st.markdown('<div class="panel-card"><div class="section-title">User View Menu</div></div>',
            unsafe_allow_html=True)
user_panel_mode = st.radio("User View Menu", ["Willingness","Allotment"],
                           horizontal=True, key="user_panel_mode")

# ── Faculty selector ─────────────────────────────────────────────── #
faculty_names = [str(r["Name"]).strip() for _,r in fac_df.iterrows()
                 if str(r["Name"]).strip() in fac_desig]
selected_name  = st.selectbox("Select Your Name", faculty_names)
selected_clean = clean(selected_name)
designation    = fac_desig.get(selected_name, "TA")
designation_key = designation.upper()

# ════════════════════════════════════════════════════════════════════ #
#  USER — ALLOTMENT VIEW
# ════════════════════════════════════════════════════════════════════ #
if user_panel_mode == "Allotment":
    st.markdown("### Your Allotment Details")

    will_df_a   = load_willingness()
    allotment_df = load_final_allotment()

    # Willingness given
    willingness_display, willingness_pairs = [], set()
    if not will_df_a.empty:
        mask = faculty_match_mask(will_df_a, selected_clean)
        wrows = will_df_a[mask].copy()
        for d, sess in zip(wrows.get("Date",[]), wrows.get("Session",[])):
            willingness_display.append(f"{format_with_day(d)} — {str(sess).strip().upper()}")
            nd = pd.to_datetime(d, dayfirst=True, errors="coerce")
            if pd.notna(nd): willingness_pairs.add((nd.date(), str(sess).strip().upper()))

    # Allotment received
    invigilation_display, invigilation_pairs = [], set()
    if not allotment_df.empty:
        mask = faculty_match_mask(allotment_df, selected_clean)
        arows = allotment_df[mask].copy()
        if not arows.empty and {"Date","Session"}.issubset(arows.columns):
            for d, sess in zip(arows["Date"], arows["Session"]):
                invigilation_display.append(f"{format_with_day(d)} — {str(sess).strip().upper()}")
                nd = pd.to_datetime(d, dayfirst=True, errors="coerce")
                if pd.notna(nd): invigilation_pairs.add((nd.date(), str(sess).strip().upper()))

    # Accommodation %
    accommodated_pct = "Not available"
    if willingness_pairs:
        matched = len(willingness_pairs.intersection(invigilation_pairs))
        accommodated_pct = f"{matched/len(willingness_pairs)*100:.2f}% ({matched}/{len(willingness_pairs)})"

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="panel-card"><div class="section-title">1) Willingness Given</div></div>',
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": willingness_display or ["Not available"]}),
                     use_container_width=True, hide_index=True)
    with c2:
        st.markdown('<div class="panel-card"><div class="section-title">2) Invigilation Dates (Final Allotment)</div></div>',
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": invigilation_display or ["Not allotted yet"]}),
                     use_container_width=True, hide_index=True)

    st.info(f"% of willingness accommodated: {accommodated_pct}")

    # WhatsApp share
    message_text = (
        f"Dear {selected_name},\n\nHere are your Examination Duty Details:\n\n"
        f"1) Willingness Given:\n" + "\n".join(willingness_display or ["Not available"]) +
        f"\n\n2) Invigilation Dates (Final Allotment):\n" +
        "\n".join(invigilation_display or ["Not allotted yet"]) +
        f"\n\nWillingness Accommodated: {accommodated_pct}\n\n"
        "– SASTRA SoME Examination Committee"
    )
    st.markdown('<div class="panel-card"><div class="section-title">📲 Share via WhatsApp</div></div>',
                unsafe_allow_html=True)
    wa_phone = st.text_input("WhatsApp Number (with country code)", placeholder="+919876543210")
    if st.button("Generate WhatsApp Link", use_container_width=True):
        if not wa_phone.strip():
            st.warning("Please enter a WhatsApp number.")
        else:
            wa_link = get_whatsapp_link(wa_phone.strip(), message_text)
            st.success("Click below to open WhatsApp with the pre-filled message.")
            st.markdown(f"""<a href="{wa_link}" target="_blank"
               style="display:inline-block;background-color:#25D366;color:white;
               padding:10px 22px;border-radius:10px;font-weight:700;
               text-decoration:none;font-size:1rem;">📲 Open WhatsApp & Send</a>""",
               unsafe_allow_html=True)
    with st.expander("Preview Message"):
        st.code(message_text, language="text")

    st.markdown("---")
    st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()

# ════════════════════════════════════════════════════════════════════ #
#  USER — WILLINGNESS SUBMISSION
# ════════════════════════════════════════════════════════════════════ #
required_count = DESIG_UI_COUNT.get(designation_key, 0)
if required_count == 0:
    st.warning("Designation rule not found. Check Faculty_with_initials.xlsx.")

# Calendar data for this faculty
if designation_key == "P":
    cal_slots = slots_online
    selection_label = "Choose Online Date"
else:
    cal_slots = slots_offline
    selection_label = "Choose Offline Date"

cal_df = pd.DataFrame([{"Date": pd.Timestamp(s["date"]), "Session": s["session"],
                         "Required": s["required"]} for s in cal_slots])

# Unique selectable dates (no valuation blocking since no V1-V5 in this simplified master)
valid_dates = sorted({s["date"] for s in cal_slots})

# Reset slot list when faculty changes
if st.session_state.selected_faculty != selected_clean:
    st.session_state.selected_faculty = selected_clean
    st.session_state.selected_slots   = []

if "picked_date" not in st.session_state or st.session_state.get("_last_faculty") != selected_clean:
    st.session_state.picked_date  = valid_dates[0] if valid_dates else None
    st.session_state._last_faculty = selected_clean

left, right = st.columns([1, 1.4])

with left:
    st.subheader("Willingness Selection")
    st.write(f"**Designation:** {designation}")
    st.write(f"**Options Required:** {required_count}")

    if designation_key == "ACP":
        st.info("ACP faculty: please select offline dates. One online + one offline duty will be assigned using your offline date preferences.")
        if st.session_state.acp_notice_shown_for != selected_clean:
            st.session_state.acp_notice_shown_for = selected_clean
            st.toast("ACP: select offline dates — online duty will be matched automatically.", icon="ℹ️")

    if not valid_dates:
        st.warning("No selectable dates available.")
    else:
        picked_date = st.selectbox(
            selection_label, valid_dates, key="picked_date",
            format_func=lambda d: pd.Timestamp(d).strftime("%d-%m-%Y (%A)"))

        avail_sessions = set()
        for s in cal_slots:
            if s["date"] == picked_date:
                avail_sessions.add(s["session"])

        at_max = len(st.session_state.selected_slots) >= required_count
        b1, b2 = st.columns(2)
        with b1:
            add_fn = st.button("Add FN", use_container_width=True,
                               disabled=("FN" not in avail_sessions) or at_max)
        with b2:
            add_an = st.button("Add AN", use_container_width=True,
                               disabled=("AN" not in avail_sessions) or at_max)

        def add_slot(session):
            existing_dates = {item["Date"] for item in st.session_state.selected_slots}
            slot = {"Date": picked_date, "Session": session}
            if picked_date in existing_dates:
                st.warning("FN and AN on the same date are not allowed. Choose a different date.")
            elif len(st.session_state.selected_slots) >= required_count:
                st.warning("Required count already reached.")
            elif slot in st.session_state.selected_slots:
                st.warning("This date-session is already selected.")
            else:
                st.session_state.selected_slots.append(slot)

        if add_fn: add_slot("FN")
        if add_an: add_slot("AN")

    st.session_state.selected_slots = st.session_state.selected_slots[:required_count]
    st.write(f"**Selected:** {len(st.session_state.selected_slots)} / {required_count}")

    selected_df = pd.DataFrame(st.session_state.selected_slots)
    if not selected_df.empty:
        selected_df = selected_df.sort_values(["Date","Session"]).reset_index(drop=True)
        selected_df.insert(0,"Sl.No", selected_df.index+1)
        selected_df["Day"]  = pd.to_datetime(selected_df["Date"]).dt.day_name()
        selected_df["Date"] = pd.to_datetime(selected_df["Date"]).dt.strftime("%d-%m-%Y")
        st.dataframe(selected_df[["Sl.No","Date","Day","Session"]], use_container_width=True, hide_index=True)

        remove_sl = st.selectbox("Select Sl.No to remove", options=selected_df["Sl.No"].tolist())
        if st.button("Remove Selected Row", use_container_width=True):
            target = selected_df[selected_df["Sl.No"]==remove_sl].iloc[0]
            td = pd.to_datetime(target["Date"], dayfirst=True).date()
            ts = target["Session"]
            st.session_state.selected_slots = [
                s for s in st.session_state.selected_slots
                if not (s["Date"]==td and s["Session"]==ts)]
            st.rerun()

    # Check submission status
    will_df_sub   = load_willingness()
    already_sub   = selected_clean in set(will_df_sub["FacultyClean"].astype(str).tolist()) \
                    if "FacultyClean" in will_df_sub.columns and not will_df_sub.empty else False
    remaining     = max(required_count - len(st.session_state.selected_slots), 0)

    st.markdown("### Submit Willingness")
    if already_sub:
        st.warning("You have already submitted your willingness.")
        st.info("Verification: Submission already exists for this faculty.")
    elif remaining == 0 and required_count > 0:
        st.success("Verification: Required count completed. You can submit now.")
    else:
        st.info(f"Verification: Select {remaining} more option(s) to enable submission.")

    submit_disabled = already_sub or len(st.session_state.selected_slots) != required_count
    if st.button("✅ Submit Willingness", disabled=submit_disabled, use_container_width=True):
        new_rows = [{"Faculty": selected_name,
                     "Date":    item["Date"].strftime("%d-%m-%Y") if hasattr(item["Date"],"strftime")
                                else pd.Timestamp(item["Date"]).strftime("%d-%m-%Y"),
                     "Session": item["Session"]}
                    for item in st.session_state.selected_slots]
        existing = will_df_sub.drop(columns=["FacultyClean"], errors="ignore")
        out_df   = pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True)
        save_willingness(out_df)
        st.toast("Thank you for submitting your willingness!", icon="✅")
        st.success("Willingness submitted successfully. The final allocation will be communicated via this portal.")
        st.session_state.selected_slots = []
        st.rerun()

with right:
    render_month_calendars(cal_df, set(), f"{'Online' if designation_key=='P' else 'Offline'} Duty Calendar")

st.markdown("---")
st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
