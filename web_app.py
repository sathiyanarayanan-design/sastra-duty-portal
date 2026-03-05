"""
SASTRA SoME Examination Duty Portal — Combined App
====================================================
Single Streamlit file combining:
  1. Faculty willingness collection
  2. Admin view (records, delete, download)
  3. Run MILP optimizer (HiGHS via scipy) directly from UI
  4. Allotment view per faculty + WhatsApp share

Required files alongside app.py:
  Faculty_Master.xlsx   — columns: Name, Designation  (+ optional V1..V5, QP_DATE cols)
  IG_Willingness.xlsx   — exam schedule (offline rows first, then Online section header)
  sastra_logo.png       — (optional) branding logo

Auto-generated files:
  Willingness.xlsx      — grows as faculty submit
  Final_Allocation.xlsx — optimizer output
  Allocation_Report.xlsx — detailed sheets

Login credentials:
  Faculty portal  : SASTRA / SASTRA
  Admin panel     : sathya
"""

import os, datetime, warnings, calendar as calmod, urllib.parse
import numpy as np
import pandas as pd
from scipy.optimize import milp, LinearConstraint, Bounds
from scipy.sparse import csc_matrix
from collections import defaultdict
import streamlit as st
import altair as alt

warnings.filterwarnings("ignore")

# ─── File Paths ──────────────────────────────────────────────── #
FACULTY_FILE      = "Faculty_Master.xlsx"
IG_FILE           = "IG_Willingness.xlsx"
WILLINGNESS_FILE  = "Willingness.xlsx"
FINAL_ALLOC_FILE  = "Final_Allocation.xlsx"
ALLOC_REPORT_FILE = "Allocation_Report.xlsx"
LOGO_FILE         = "sastra_logo.png"

# ─── Designation Rules (optimizer) ───────────────────────────── #
DESIG_RULES = {
    "P":   (1, 1, ["Online"]),
    "ACP": (2, 3, ["Online", "Offline"]),
    "SAP": (3, 3, ["Offline"]),
    "AP3": (3, 3, ["Offline"]),
    "AP2": (3, 3, ["Offline"]),
    "TA":  (3, 3, ["Offline"]),
    "RA":  (4, 4, ["Offline"]),
}

# Options required per designation (willingness portal UI)
DUTY_STRUCTURE = {
    "P": 3, "ACP": 5, "SAP": 7, "AP3": 7, "AP2": 7, "TA": 9, "RA": 9,
}

# Willingness score tiers
W_EXACT      = 100
W_FLIP       = 70
W_ADJ        = 40
W_ACP_ONLINE = 60
W_NON_SUB    = 5
PENALTY      = 30

# ─── Page Config ─────────────────────────────────────────────── #
st.set_page_config(page_title="SASTRA Duty Portal", layout="wide")

st.markdown("""
<style>
.stApp { background: #f4f7fb; }
.main .block-container { max-width: 1200px; padding-top: 1.2rem; padding-bottom: 1.5rem; }
.secure-card {
    background: linear-gradient(180deg,#ffffff 0%,#f8fafc 100%);
    border:1px solid #dbe3ef; border-radius:14px; padding:16px 18px;
    box-shadow:0 10px 24px rgba(15,23,42,0.08); margin-bottom:12px;
}
.panel-card {
    background:#ffffff; border:1px solid #e2e8f0; border-radius:14px;
    padding:14px 16px; box-shadow:0 8px 20px rgba(15,23,42,0.06); margin-bottom:10px;
}
.secure-title { font-size:1.08rem; font-weight:700; color:#0f172a; margin-bottom:0.2rem; }
.secure-sub   { font-size:0.93rem; color:#334155; margin-bottom:0; }
.section-title{ font-size:1rem; font-weight:700; color:#0b3a67; margin-bottom:0.35rem; }
.stButton>button        { border-radius:10px; border:1px solid #cbd5e1; font-weight:600; }
.stDownloadButton>button{ border-radius:10px; font-weight:600; }
.blink-notice {
    font-weight:700; color:#800000; padding:10px 12px;
    border:2px solid #800000; background:#fffaf5; border-radius:6px;
    animation:blinkPulse 2.4s ease-in-out infinite;
}
@keyframes blinkPulse{0%{opacity:1;}50%{opacity:0.35;}100%{opacity:1;}}
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════ #
#                     HELPER FUNCTIONS                           #
# ═══════════════════════════════════════════════════════════════ #

def clean(x):
    return str(x).strip().lower()

def normalize_session(value):
    t = str(value).strip().upper()
    if t in {"FN","FORENOON","MORNING","AM"}: return "FN"
    if t in {"AN","AFTERNOON","EVENING","PM"}: return "AN"
    return t

def load_excel_safe(path):
    if not os.path.exists(path):
        st.error(f"Required file not found: **{path}**")
        st.stop()
    return pd.read_excel(path)

def normalize_duty_df(df):
    df = df.copy()
    df.columns = df.columns.str.strip()
    df.rename(columns={df.columns[0]:"Date", df.columns[1]:"Session", df.columns[2]:"Required"}, inplace=True)
    df["Date"]     = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df             = df.dropna(subset=["Date"]).copy()
    df["Session"]  = df["Session"].apply(normalize_session)
    df["Required"] = pd.to_numeric(df["Required"], errors="coerce").fillna(1).astype(int)
    return df

def load_willingness():
    if os.path.exists(WILLINGNESS_FILE):
        df = pd.read_excel(WILLINGNESS_FILE)
        if "Faculty" not in df.columns:
            df["Faculty"] = ""
        df["FacultyClean"] = df["Faculty"].apply(clean)
        return df
    return pd.DataFrame(columns=["Faculty","Date","Session","FacultyClean"])

def load_final_allotment():
    if os.path.exists(FINAL_ALLOC_FILE):
        try:
            return pd.read_excel(FINAL_ALLOC_FILE)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()

def valuation_dates_for_faculty(faculty_row):
    dates = []
    for col in ["V1","V2","V3","V4","V5"]:
        if col in faculty_row.index and pd.notna(faculty_row[col]):
            dates.append(pd.to_datetime(faculty_row[col], dayfirst=True).date())
    return sorted(set(dates))

def collect_qp_feedback_dates(faculty_row):
    qp_dates = []
    for col in faculty_row.index:
        ct = str(col).strip().upper()
        if "QP" in ct and "DATE" in ct:
            val = faculty_row[col]
            if pd.notna(val):
                dt = pd.to_datetime(val, dayfirst=True, errors="coerce")
                if pd.notna(dt):
                    qp_dates.append(dt.strftime("%d-%m-%Y"))
    return sorted(set(qp_dates))

def format_with_day(date_text):
    dt = pd.to_datetime(date_text, dayfirst=True, errors="coerce")
    if pd.isna(dt): return str(date_text).strip()
    return f"{dt.strftime('%d-%m-%Y')} ({dt.strftime('%A')})"

def faculty_match_mask(df, selected_clean):
    if df.empty: return pd.Series([], dtype=bool)
    name_cols = [c for c in df.columns
                 if "name" in str(c).strip().lower() or "faculty" in str(c).strip().lower()]
    if not name_cols:
        return pd.Series([False]*len(df), index=df.index)
    mask = pd.Series([False]*len(df), index=df.index)
    for col in name_cols:
        mask = mask | (df[col].astype(str).apply(clean) == selected_clean)
    return mask

def demand_category(r):
    if r < 3: return "Low (<3)"
    if r <= 7: return "Medium (3-7)"
    return "High (>7)"

def build_month_calendar_frame(duty_df, valuation_dates, year, month):
    sg = duty_df.groupby(["Date","Session"], as_index=False)["Required"].sum()
    demand_map = {
        (d.date(), str(s).upper()): int(r)
        for d, s, r in zip(sg["Date"], sg["Session"], sg["Required"])
    }
    ms = pd.Timestamp(year=year, month=month, day=1)
    me = ms + pd.offsets.MonthEnd(0)
    fw = ms.weekday()
    WD = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    rows = []
    for dt in pd.date_range(ms, me, freq="D"):
        wk = ((dt.day + fw - 1) // 7) + 1
        do = dt.date()
        for sess in ["FN","AN"]:
            req = demand_map.get((do, sess), 0)
            if do in valuation_dates:    cat = "Valuation Locked"
            elif req == 0:               cat = "No Duty"
            else:                        cat = demand_category(req)
            rows.append({"Date":dt,"Week":wk,"Weekday":WD[dt.weekday()],
                         "DayNum":dt.day,"Session":sess,"Required":req,
                         "Category":cat,"DateLabel":dt.strftime("%d-%m-%Y")})
    return pd.DataFrame(rows)

def render_month_calendars(duty_df, valuation_dates, title):
    st.markdown(f"#### {title}")
    if duty_df.empty:
        st.info("No slot data available.")
        return
    months = sorted({(d.year, d.month) for d in duty_df["Date"]})
    cscale = alt.Scale(
        domain=["No Duty","Low (<3)","Medium (3-7)","High (>7)","Valuation Locked"],
        range=["#ececec","#2ca02c","#f1c40f","#d62728","#ff69b4"],
    )
    st.markdown("**Legend:** ⬜ No Duty  🟩 Low (<3)  🟨 Medium (3–7)  🟥 High (>7)  🩷 Valuation Locked")
    for year, month in months:
        frame = build_month_calendar_frame(duty_df, set(valuation_dates), year, month)
        high  = int((frame["Category"]=="High (>7)").sum())
        st.markdown(f"**{calmod.month_name[month]} {year}**")
        st.caption(f"High-demand slots (>7 required): {high}")
        base = alt.Chart(frame).encode(
            x=alt.X("Weekday:N", sort=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"], title=""),
            xOffset=alt.XOffset("Session:N", sort=["FN","AN"]),
            y=alt.Y("Week:O", sort="ascending", title=""),
            tooltip=[alt.Tooltip("DateLabel:N",title="Date"),
                     alt.Tooltip("Session:N",title="Session"),
                     alt.Tooltip("Required:Q",title="Demand"),
                     alt.Tooltip("Category:N",title="Category")],
        )
        rect = base.mark_rect(stroke="white").encode(
            color=alt.Color("Category:N", scale=cscale,
                            legend=alt.Legend(title="Legend")))
        day_text = (
            alt.Chart(frame[frame["Session"]=="FN"])
            .mark_text(color="black", fontSize=11, dy=-6)
            .encode(x=alt.X("Weekday:N",sort=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]),
                    y=alt.Y("Week:O",sort="ascending"),
                    text=alt.Text("DayNum:Q"))
        )
        st.altair_chart((rect + day_text).properties(height=230), use_container_width=True)
        st.caption("Left half of each day = FN, right half = AN.")

def get_whatsapp_link(phone, message):
    p = str(phone).strip().replace("+","").replace(" ","").replace("-","")
    return f"https://wa.me/{p}?text={urllib.parse.quote(message)}"

def build_delivery_message(name, will_list, val_list, inv_list, qp_list, pct):
    return "\n".join([
        f"Dear {name},", "",
        "Examination Duty Details:", "",
        "1) Invigilation Dates (Final Allotment):",
        *(inv_list or ["Not allotted yet"]), "",
        "2) Valuation Dates (Full Day):",
        *(val_list or ["Not available"]), "",
        "3) QP Feedback Dates:",
        *(qp_list or ["Not available"]), "",
        f"Willingness accommodated: {pct}", "",
        "- SASTRA SoME Examination Committee",
    ])

def render_branding_header(show_logo=True):
    if show_logo and os.path.exists(LOGO_FILE):
        c1, c2, c3 = st.columns([2,1,2])
        with c2: st.image(LOGO_FILE, width=180)
    st.markdown("<h2 style='text-align:center;margin-bottom:0.25rem;'>"
                "SASTRA SoME End Semester Examination Duty Portal</h2>",
                unsafe_allow_html=True)
    st.markdown("<h4 style='text-align:center;margin-top:0;'>"
                "School of Mechanical Engineering</h4>", unsafe_allow_html=True)
    st.markdown("---")


# ═══════════════════════════════════════════════════════════════ #
#               OPTIMIZER FUNCTION (MILP via HiGHS)              #
# ═══════════════════════════════════════════════════════════════ #

def parse_ig_section(raw_df, start, end, duty_type):
    """Parse exam slots from IG_Willingness.xlsx section."""
    slots = []
    for i in range(start, end):
        row = raw_df.iloc[i]
        d, sess, req = row.iloc[0], row.iloc[1], row.iloc[2]
        if pd.isna(d) or str(sess).strip().upper() not in ("FN","AN"):
            continue
        try:    date = pd.to_datetime(d).date()
        except: continue
        try:    required = max(int(float(req)), 0)
        except: required = 1
        slots.append({"date":date,"session":str(sess).strip().upper(),
                      "required":required,"type":duty_type})
    return slots

def run_optimizer(log_box):
    """
    Runs HiGHS MILP optimizer.
    Reads: Faculty_Master.xlsx, Willingness.xlsx, IG_Willingness.xlsx
    Writes: Final_Allocation.xlsx, Allocation_Report.xlsx
    Returns: (alloc_df, summary_df, slot_df, desig_df)
    """
    log_lines = []
    def log(msg=""):
        log_lines.append(msg)
        log_box.code("\n".join(log_lines), language="text")

    log("=" * 62)
    log("  SASTRA SoME Duty Optimizer — v4  (HiGHS MILP)")
    log("=" * 62)

    # ── Load Faculty ── #
    fac_raw = pd.read_excel(FACULTY_FILE)
    fac_raw.columns = fac_raw.columns.str.strip()
    fac_raw.rename(columns={fac_raw.columns[0]:"Name",
                             fac_raw.columns[1]:"Designation"}, inplace=True)

    ALL_FACULTY = [str(r["Name"]).strip() for _, r in fac_raw.iterrows()]
    FAC_IDX     = {n: i for i, n in enumerate(ALL_FACULTY)}
    N_FAC       = len(ALL_FACULTY)

    fac_desig = {}
    for _, row in fac_raw.iterrows():
        name  = str(row["Name"]).strip()
        desig = str(row["Designation"]).strip().upper()
        fac_desig[name] = desig if desig in DESIG_RULES else "TA"

    desig_groups = defaultdict(list)
    for name, d in fac_desig.items():
        desig_groups[d].append(name)

    # ── Load Willingness ── #
    will_df = load_willingness()
    if "Date" in will_df.columns:
        will_df["Date"] = pd.to_datetime(will_df["Date"], dayfirst=True, errors="coerce")
        will_df["Session"] = will_df["Session"].astype(str).str.strip().str.upper()
        will_df = will_df.dropna(subset=["Date"])

    submitted_faculty = set(will_df["Faculty"].str.strip().unique()) if ("Faculty" in will_df.columns and not will_df.empty) else set()
    non_submitted     = [n for n in ALL_FACULTY if n not in submitted_faculty]

    log(f"\n  Faculty total    : {N_FAC}")
    log(f"  Submitted will.  : {len(submitted_faculty)}")
    log(f"  Non-submitted    : {len(non_submitted)}")
    if non_submitted:
        log("  Non-submitted (auto-assigned with low priority):")
        for n in non_submitted:
            log(f"    • {n}  [{fac_desig.get(n,'?')}]")

    # ── Parse Exam Slots ── #
    raw = pd.read_excel(IG_FILE, header=None)
    online_header_row = None
    for i in range(len(raw)):
        cell = str(raw.iloc[i, 0])
        if "GCR Online" in cell or "online exams" in cell.lower():
            online_header_row = i
            break

    offline_end  = (online_header_row - 1) if online_header_row else len(raw)
    online_start = (online_header_row + 2) if online_header_row else None

    slots_offline = parse_ig_section(raw, 1, offline_end, "Offline")
    slots_online  = parse_ig_section(raw, online_start, len(raw), "Online") if online_start else []
    ALL_SLOTS     = slots_offline + slots_online
    N_SLOTS       = len(ALL_SLOTS)

    log(f"\n  Exam slots: {N_SLOTS}  ({len(slots_offline)} offline + {len(slots_online)} online)")
    log(f"  Assignments needed: {sum(s['required'] for s in ALL_SLOTS)}")

    # ── Build Expanded Willingness ── #
    fac_expanded = defaultdict(dict)   # name -> {(date,sess,type): score}

    # Step 1: exact from submitted CSV
    for _, row in will_df.iterrows():
        name = str(row.get("Faculty","")).strip()
        if name not in FAC_IDX: continue
        date = row["Date"].date()
        sess = str(row["Session"]).strip().upper()
        desig   = fac_desig.get(name, "TA")
        allowed = DESIG_RULES[desig][2]
        for dtype in allowed:
            key = (date, sess, dtype)
            fac_expanded[name][key] = max(fac_expanded[name].get(key, 0), W_EXACT)
        # ACP: offline date also counts for online
        if desig == "ACP":
            for s2 in ["FN","AN"]:
                ok = (date, s2, "Online")
                fac_expanded[name][ok] = max(fac_expanded[name].get(ok, 0), W_ACP_ONLINE)

    # Step 2: session flip FN↔AN same date
    for name in list(fac_expanded.keys()):
        for (date, sess, dtype), score in list(fac_expanded[name].items()):
            if score < W_FLIP: continue
            opp = "AN" if sess == "FN" else "FN"
            fk = (date, opp, dtype)
            fac_expanded[name][fk] = max(fac_expanded[name].get(fk, 0), W_FLIP)

    # Step 3: ±1 adjacent day
    for name in list(fac_expanded.keys()):
        for (date, sess, dtype), score in list(fac_expanded[name].items()):
            if score < W_FLIP: continue
            for delta in [-1, +1]:
                adj = date + datetime.timedelta(days=delta)
                for as2 in ["FN","AN"]:
                    ak = (adj, as2, dtype)
                    fac_expanded[name][ak] = max(fac_expanded[name].get(ak, 0), W_ADJ)

    # Step 4: non-submitted — willing for all allowed slots (low priority)
    for name in non_submitted:
        desig   = fac_desig.get(name, "TA")
        allowed = DESIG_RULES[desig][2]
        for slot in ALL_SLOTS:
            if slot["type"] in allowed:
                key = (slot["date"], slot["session"], slot["type"])
                if key not in fac_expanded[name]:
                    fac_expanded[name][key] = W_NON_SUB

    # ── Coverage Check ── #
    zero_slots = []
    for slot in ALL_SLOTS:
        key = (slot["date"], slot["session"], slot["type"])
        eligible = [n for n in ALL_FACULTY
                    if key in fac_expanded[n]
                    and slot["type"] in DESIG_RULES[fac_desig[n]][2]]
        if len(eligible) < slot["required"]:
            ds = pd.Timestamp(slot["date"]).strftime("%d-%m-%Y")
            zero_slots.append(f"  {ds} {slot['session']} {slot['type']}: "
                              f"need {slot['required']}, eligible {len(eligible)}")
    if zero_slots:
        log("\n  ⚠ Slots with fewer eligible than required:")
        for z in zero_slots: log(z)
    else:
        log("\n  ✓ Every slot has sufficient eligible faculty")

    # ── Build MILP ── #
    def var(f, s): return f * N_SLOTS + s
    N_VARS = N_FAC * N_SLOTS

    c  = np.zeros(N_VARS)
    lb = np.zeros(N_VARS)
    ub = np.ones(N_VARS)

    for f_idx, f_name in enumerate(ALL_FACULTY):
        desig   = fac_desig[f_name]
        allowed = DESIG_RULES[desig][2]
        has_sub = f_name in submitted_faculty
        for s_idx, slot in enumerate(ALL_SLOTS):
            dtype = slot["type"]
            if dtype not in allowed:
                ub[var(f_idx, s_idx)] = 0.0
                continue
            key   = (slot["date"], slot["session"], dtype)
            score = fac_expanded[f_name].get(key, 0)
            if score > 0:
                c[var(f_idx, s_idx)] = -float(score)
            elif has_sub:
                c[var(f_idx, s_idx)] = float(PENALTY)

    rows_A, cols_A, data_A = [], [], []
    b_lo, b_hi = [], []
    nc = [0]

    def add_con(vids, coeffs, lo, hi):
        for vi, co in zip(vids, coeffs):
            rows_A.append(nc[0]); cols_A.append(vi); data_A.append(float(co))
        b_lo.append(float(lo)); b_hi.append(float(hi))
        nc[0] += 1

    online_idxs  = [i for i,s in enumerate(ALL_SLOTS) if s["type"]=="Online"]
    offline_idxs = [i for i,s in enumerate(ALL_SLOTS) if s["type"]=="Offline"]

    # C1: slot demand exactly met
    for s_idx, slot in enumerate(ALL_SLOTS):
        add_con([var(f,s_idx) for f in range(N_FAC)], [1]*N_FAC,
                slot["required"], slot["required"])

    # C2: faculty duty count min..max
    for f_idx, f_name in enumerate(ALL_FACULTY):
        dr = DESIG_RULES[fac_desig[f_name]]
        add_con([var(f_idx,s) for s in range(N_SLOTS)], [1]*N_SLOTS, dr[0], dr[1])

    # C3: no double-booking (same faculty, same date, same type)
    date_type_slots = defaultdict(list)
    for s_idx, slot in enumerate(ALL_SLOTS):
        date_type_slots[(slot["date"], slot["type"])].append(s_idx)
    for f_idx in range(N_FAC):
        for (dt2, dtype2), s_idxs in date_type_slots.items():
            if len(s_idxs) > 1:
                add_con([var(f_idx,si) for si in s_idxs], [1]*len(s_idxs), 0, 1)

    # C4: P exactly 1 online duty
    for f_name in desig_groups["P"]:
        f_idx = FAC_IDX[f_name]
        add_con([var(f_idx,si) for si in online_idxs], [1]*len(online_idxs), 1, 1)

    # C5: ACP ≥1 online AND ≥1 offline
    for f_name in desig_groups["ACP"]:
        f_idx = FAC_IDX[f_name]
        if online_idxs:
            add_con([var(f_idx,si) for si in online_idxs],  [1]*len(online_idxs),  1, len(online_idxs))
        if offline_idxs:
            add_con([var(f_idx,si) for si in offline_idxs], [1]*len(offline_idxs), 1, len(offline_idxs))

    A = csc_matrix((data_A,(rows_A,cols_A)), shape=(nc[0], N_VARS))
    constraints = LinearConstraint(A, b_lo, b_hi)
    integrality = np.ones(N_VARS)
    bounds      = Bounds(lb=lb, ub=ub)

    log(f"\n  Variables  : {N_VARS}")
    log(f"  Constraints: {nc[0]}")
    log(f"\n  Solving HiGHS MILP (time limit: 300 s)...")

    result = milp(c=c, constraints=constraints, integrality=integrality,
                  bounds=bounds, options={"disp":False,"time_limit":300})

    log(f"  HiGHS status: {result.message}")

    # ── Extract Solution ── #
    assigned_slots = []
    if result.status in (0, 1):
        x = np.round(result.x).astype(int)
        for f_idx, f_name in enumerate(ALL_FACULTY):
            for s_idx, slot in enumerate(ALL_SLOTS):
                if x[var(f_idx, s_idx)] == 1:
                    key   = (slot["date"], slot["session"], slot["type"])
                    score = fac_expanded[f_name].get(key, 0)
                    if f_name in non_submitted:    wb = "Auto-Assigned"
                    elif score >= W_EXACT:         wb = "Willingness-Exact"
                    elif score >= W_ACP_ONLINE:    wb = "Willingness-ACPOnline"
                    elif score >= W_FLIP:          wb = "Willingness-SessionFlip"
                    elif score >= W_ADJ:           wb = "Willingness-±1Day"
                    elif score == W_NON_SUB:       wb = "Auto-Assigned"
                    else:                          wb = "OR-Assigned"
                    assigned_slots.append({
                        "Name":f_name, "Date":slot["date"],
                        "Session":slot["session"], "Type":slot["type"],
                        "Allocated_By":wb,
                    })
        method = "MILP Optimal (HiGHS)"
    else:
        log("\n  ⚠ MILP infeasible or no solution — running greedy fallback...")
        method = "Greedy Fallback"
        assigned_count = defaultdict(int)
        used_dt        = defaultdict(set)

        def duty_rem(n): return DESIG_RULES[fac_desig[n]][0] - assigned_count[n]
        def can_do(n, d, t): return (d,t) not in used_dt[n]
        def type_ok(n, t): return t in DESIG_RULES[fac_desig[n]][2]

        for slot in sorted(ALL_SLOTS, key=lambda x: -x["required"]):
            date, sess, req, dtype = slot["date"],slot["session"],slot["required"],slot["type"]
            key = (date, sess, dtype)
            scored = sorted(
                [(n, fac_expanded[n].get(key,0)) for n in ALL_FACULTY
                 if type_ok(n,dtype) and duty_rem(n)>0 and can_do(n,date,dtype)],
                key=lambda x: (-x[1], assigned_count[x[0]])
            )
            for name, score in scored[:req]:
                assigned_count[name] += 1
                used_dt[name].add((date,dtype))
                if name in non_submitted:    wb="Auto-Assigned"
                elif score >= W_EXACT:       wb="Willingness-Exact"
                elif score >= W_ACP_ONLINE:  wb="Willingness-ACPOnline"
                elif score >= W_FLIP:        wb="Willingness-SessionFlip"
                elif score >= W_ADJ:         wb="Willingness-±1Day"
                else:                        wb="OR-Assigned"
                assigned_slots.append({"Name":name,"Date":date,"Session":sess,"Type":dtype,"Allocated_By":wb})

        # Gap fill for remaining faculty requirements
        for name in ALL_FACULTY:
            for slot in sorted(ALL_SLOTS, key=lambda x: x["date"]):
                if duty_rem(name) <= 0: break
                d2, s2, t2 = slot["date"],slot["session"],slot["type"]
                if not type_ok(name,t2): continue
                if not can_do(name,d2,t2): continue
                assigned_count[name] += 1
                used_dt[name].add((d2,t2))
                assigned_slots.append({"Name":name,"Date":d2,"Session":s2,"Type":t2,"Allocated_By":"Gap-Fill"})

    # ── Build Result DataFrames ── #
    alloc_df = pd.DataFrame(assigned_slots)
    if alloc_df.empty:
        log("\n  ⚠ No assignments generated.")
        raise RuntimeError("Optimizer produced no assignments. Check input data.")

    alloc_df["Date"] = pd.to_datetime(alloc_df["Date"]).dt.strftime("%d-%m-%Y")
    alloc_df = alloc_df.sort_values(["Date","Session","Name"]).reset_index(drop=True)
    alloc_df.insert(0, "Sl.No", alloc_df.index + 1)

    # Per-faculty summary
    summary_rows = []
    for name in ALL_FACULTY:
        desig   = fac_desig[name]
        dr      = DESIG_RULES[desig]
        rows_f  = alloc_df[alloc_df["Name"]==name]
        assigned= len(rows_f)
        ab      = rows_f["Allocated_By"]
        exact   = int((ab=="Willingness-Exact").sum())
        acpo    = int((ab=="Willingness-ACPOnline").sum())
        flip    = int((ab=="Willingness-SessionFlip").sum())
        adj     = int((ab=="Willingness-±1Day").sum())
        auto    = int(ab.isin(["Auto-Assigned","OR-Assigned","Gap-Fill"]).sum())
        on_cnt  = int((rows_f["Type"]=="Online").sum())
        off_cnt = int((rows_f["Type"]=="Offline").sum())
        summary_rows.append({
            "Name":name, "Designation":desig,
            "Submitted":"Yes" if name in submitted_faculty else "No",
            "Required_Duties":dr[0], "Assigned_Duties":assigned,
            "Willingness_Total":exact+acpo+flip+adj,
            "Exact_Match":exact,"ACP_Online":acpo,
            "Session_Flip":flip,"Adj_Day":adj,
            "Auto_Assigned":auto,"Online":on_cnt,"Offline":off_cnt,
            "Gap":max(dr[0]-assigned,0),
        })
    summary_df = pd.DataFrame(summary_rows)

    # Slot verification
    slot_check = []
    for slot in ALL_SLOTS:
        ds = pd.Timestamp(slot["date"]).strftime("%d-%m-%Y")
        na = len(alloc_df[
            (alloc_df["Date"]==ds) &
            (alloc_df["Session"]==slot["session"]) &
            (alloc_df["Type"]==slot["type"])
        ])
        slot_check.append({
            "Date":ds,"Session":slot["session"],"Type":slot["type"],
            "Required":slot["required"],"Assigned":na,
            "Status":"✓" if na>=slot["required"] else f"✗ short {slot['required']-na}",
        })
    slot_df = pd.DataFrame(slot_check)

    # Designation summary
    desig_rows = []
    for desig in DESIG_RULES:
        sub = summary_df[summary_df["Designation"]==desig]
        if sub.empty: continue
        on = int(sub["Online"].sum()); off = int(sub["Offline"].sum())
        dr = DESIG_RULES[desig]
        desig_rows.append({
            "Designation":desig,"Faculty_Count":len(sub),
            "Duties_Per_Person":dr[0],"Total_Required":dr[0]*len(sub),
            "Total_Assigned":on+off,
            "Willingness_Matched":int(sub["Willingness_Total"].sum()),
            "Auto_Assigned":int(sub["Auto_Assigned"].sum()),
            "Online":on,"Offline":off,
        })
    desig_df = pd.DataFrame(desig_rows)

    # Save files
    alloc_df.to_excel(FINAL_ALLOC_FILE, index=False)
    with pd.ExcelWriter(ALLOC_REPORT_FILE, engine="openpyxl") as w:
        desig_df.to_excel(w,   sheet_name="Designation_Summary", index=False)
        summary_df.to_excel(w, sheet_name="Faculty_Summary",     index=False)
        slot_df.to_excel(w,    sheet_name="Slot_Verification",   index=False)
        alloc_df.to_excel(w,   sheet_name="Full_Allocation",     index=False)

    # Final summary log
    total = len(alloc_df)
    ab    = alloc_df["Allocated_By"]
    exact = int((ab=="Willingness-Exact").sum())
    acpo  = int((ab=="Willingness-ACPOnline").sum())
    flip  = int((ab=="Willingness-SessionFlip").sum())
    adj   = int((ab=="Willingness-±1Day").sum())
    auto  = int(ab.isin(["Auto-Assigned","OR-Assigned","Gap-Fill"]).sum())
    unmet = slot_df[~slot_df["Status"].str.startswith("✓")]
    gaps  = summary_df[summary_df["Gap"]>0]

    log(f"\n{'='*62}")
    log(f"  RESULTS  [{method}]")
    log(f"{'='*62}")
    log(f"  Total assignments      : {total}")
    log(f"  ├─ Exact willingness   : {exact}  ({exact/total*100:.1f}%)")
    log(f"  ├─ ACP offline→online  : {acpo}  ({acpo/total*100:.1f}%)")
    log(f"  ├─ Session flip FN↔AN  : {flip}  ({flip/total*100:.1f}%)")
    log(f"  ├─ Adjacent day ±1     : {adj}  ({adj/total*100:.1f}%)")
    log(f"  └─ Auto-assigned       : {auto}  ({auto/total*100:.1f}%)")
    log(f"\n  Slot fulfilment : {len(slot_df)-len(unmet)}/{len(slot_df)}"
        + (" ✓ ALL MET!" if len(unmet)==0 else f"  ⚠ {len(unmet)} unmet"))
    log(f"  Faculty targets : {len(summary_df)-len(gaps)}/{len(summary_df)}"
        + (" ✓ ALL MET!" if len(gaps)==0 else f"  ⚠ {len(gaps)} short"))

    acp_sub = summary_df[summary_df["Designation"]=="ACP"]
    acp_ok  = len(acp_sub[(acp_sub["Online"]>=1) & (acp_sub["Offline"]>=1)])
    log(f"  ACP (≥1 online + ≥1 offline): {acp_ok}/{len(acp_sub)} satisfied")
    log(f"\n  Files saved:")
    log(f"    {FINAL_ALLOC_FILE}")
    log(f"    {ALLOC_REPORT_FILE}")

    return alloc_df, summary_df, slot_df, desig_df


# ═══════════════════════════════════════════════════════════════ #
#                LOAD IG SLOTS FOR CALENDAR (cached)             #
# ═══════════════════════════════════════════════════════════════ #

@st.cache_data
def load_ig_slots():
    if not os.path.exists(IG_FILE):
        return (pd.DataFrame(columns=["Date","Session","Required"]),
                pd.DataFrame(columns=["Date","Session","Required"]))
    raw = pd.read_excel(IG_FILE, header=None)
    online_hr = None
    for i in range(len(raw)):
        cell = str(raw.iloc[i, 0])
        if "GCR Online" in cell or "online exams" in cell.lower():
            online_hr = i; break
    off_end = (online_hr - 1) if online_hr else len(raw)
    on_start= (online_hr + 2) if online_hr else None

    def to_df(slots):
        if not slots:
            return pd.DataFrame(columns=["Date","Session","Required"])
        df = pd.DataFrame(slots)
        df["Date"]     = pd.to_datetime(df["date"])
        df["Session"]  = df["session"]
        df["Required"] = df["required"]
        return df[["Date","Session","Required"]]

    return (to_df(parse_ig_section(raw, 1, off_end, "Offline")),
            to_df(parse_ig_section(raw, on_start, len(raw), "Online") if on_start else []))


# ═══════════════════════════════════════════════════════════════ #
#                   SESSION STATE INIT                           #
# ═══════════════════════════════════════════════════════════════ #
_defaults = {
    "logged_in": False,
    "admin_authenticated": False,
    "panel_mode": "User View",
    "user_panel_mode": "Willingness",
    "selected_faculty": "",
    "selected_slots": [],
    "acp_notice_shown_for": "",
    "confirm_delete_willingness": False,
    "optimizer_ran": False,
}
for k, v in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ═══════════════════════════════════════════════════════════════ #
#                        LOGIN WALL                              #
# ═══════════════════════════════════════════════════════════════ #
if not st.session_state.logged_in:
    render_branding_header(show_logo=True)
    _, c2, _ = st.columns([1,2,1])
    with c2:
        st.markdown('<div class="secure-card"><div class="secure-title">🔒 Faculty Login</div>'
                    '<p class="secure-sub">Enter your credentials to access the portal.</p></div>',
                    unsafe_allow_html=True)
        un = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        if st.button("Sign In", use_container_width=True):
            if un == "SASTRA" and pw == "SASTRA":
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("Invalid credentials.")
    st.markdown("---")
    st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()


# ═══════════════════════════════════════════════════════════════ #
#                   LOAD CORE DATA                               #
# ═══════════════════════════════════════════════════════════════ #
faculty_df = load_excel_safe(FACULTY_FILE)
faculty_df.columns = faculty_df.columns.str.strip()
faculty_df.rename(columns={faculty_df.columns[0]:"Name",
                            faculty_df.columns[1]:"Designation"}, inplace=True)
faculty_df["Clean"] = faculty_df["Name"].apply(clean)

offline_df, online_df = load_ig_slots()


# ═══════════════════════════════════════════════════════════════ #
#                   HEADER + NOTICE BANNER                       #
# ═══════════════════════════════════════════════════════════════ #
render_branding_header(show_logo=False)
st.markdown(
    "<div class='blink-notice'><strong>Note:</strong> The University Examination Committee "
    "sincerely appreciates your cooperation. Every effort will be made to accommodate your "
    "willingness while ensuring adherence to institutional requirements. The final duty "
    "allocation is carried out using AI-assisted MILP optimization.</div>",
    unsafe_allow_html=True,
)

# ─── Control Panel ─── #
st.markdown("")
st.markdown('<div class="panel-card"><div class="section-title">Control Panel</div>'
            '<p class="secure-sub">Select Admin View for administrative functions or '
            'User View for willingness submission / allotment.</p></div>',
            unsafe_allow_html=True)
panel_mode = st.radio("Main Menu", ["User View","Admin View"],
                      horizontal=True, key="panel_mode")


# ═══════════════════════════════════════════════════════════════ #
#                       ADMIN VIEW                               #
# ═══════════════════════════════════════════════════════════════ #
if panel_mode == "Admin View":
    st.markdown('<div class="secure-card"><div class="secure-title">🔒 Admin View (Secure Access)</div>'
                '<p class="secure-sub">Protected administrative functions. Authenticate to continue.</p></div>',
                unsafe_allow_html=True)

    if not st.session_state.admin_authenticated:
        ap = st.text_input("Admin Password", type="password", key="admin_password_input")
        if st.button("Unlock Admin View", use_container_width=True):
            if ap == "sathya":
                st.session_state.admin_authenticated = True
                st.rerun()
            else:
                st.error("Invalid admin password.")
    else:
        st.success("✅ Admin view unlocked.")
        tab1, tab2, tab3 = st.tabs([
            "📋 Willingness Records",
            "🤖 Run Optimizer",
            "📊 View Results",
        ])

        # ──────────────────────────────────────────────
        with tab1:
            st.markdown("### Submitted Willingness Records")
            w_admin = load_willingness().drop(columns=["FacultyClean"], errors="ignore")
            if w_admin.empty:
                st.info("No willingness submissions yet.")
            else:
                vdf = w_admin.copy().reset_index(drop=True)
                vdf.insert(0, "Sl.No", vdf.index + 1)
                # Metrics
                submitted_count = vdf["Faculty"].nunique() if "Faculty" in vdf.columns else 0
                total_fac       = len(faculty_df)
                not_submitted   = total_fac - submitted_count
                c1, c2, c3 = st.columns(3)
                c1.metric("Faculty Submitted", submitted_count)
                c2.metric("Not Submitted", not_submitted)
                c3.metric("Total Rows", len(vdf))
                st.dataframe(vdf, use_container_width=True, hide_index=True)
                st.download_button("⬇ Download Willingness CSV",
                                   data=vdf.to_csv(index=False).encode("utf-8"),
                                   file_name="Willingness_Admin_View.csv",
                                   mime="text/csv")

            st.markdown("---")
            st.markdown("#### ⚠ Delete All Willingness Records")
            st.checkbox("I confirm deletion of all submitted willingness records",
                        key="confirm_delete_willingness")
            if st.button("Delete All Willingness", type="primary", key="del_will_btn"):
                if st.session_state.confirm_delete_willingness:
                    pd.DataFrame(columns=["Faculty","Date","Session"]).to_excel(WILLINGNESS_FILE, index=False)
                    st.success("All willingness records deleted.")
                    st.session_state.confirm_delete_willingness = False
                    st.rerun()
                else:
                    st.error("Please confirm the deletion checkbox before proceeding.")

        # ──────────────────────────────────────────────
        with tab2:
            st.markdown("### 🤖 Run Allocation Optimizer")
            st.markdown("""
**Required files in app directory:**
- `Faculty_Master.xlsx` — Name, Designation columns (rows must be in designation-group order)
- `IG_Willingness.xlsx` — Exam slot schedule (offline rows first, then Online section header)
- `Willingness.xlsx`    — Auto-generated from faculty portal submissions
            """)

            required_files = [FACULTY_FILE, IG_FILE, WILLINGNESS_FILE]
            missing = [f for f in required_files if not os.path.exists(f)]
            if missing:
                st.error(f"Missing required file(s): {', '.join(missing)}")
            else:
                w_now = load_willingness()
                sub_cnt = w_now["Faculty"].nunique() if "Faculty" in w_now.columns and not w_now.empty else 0
                tot_fac = len(faculty_df)
                c1, c2, c3 = st.columns(3)
                c1.metric("Faculty in Master", tot_fac)
                c2.metric("Willingness Submitted", f"{sub_cnt}/{tot_fac}")
                c3.metric("Willingness Rows", len(w_now))
                st.success("All required files found. Ready to optimise.")

                if st.button("▶ Run Optimizer", type="primary",
                             use_container_width=True, key="run_opt_btn"):
                    log_box = st.empty()
                    with st.spinner("Running MILP optimization — this may take several minutes..."):
                        try:
                            alloc_df, summary_df, slot_df, desig_df = run_optimizer(log_box)
                            st.session_state.optimizer_ran = True
                            st.success("✅ Optimization complete! See the **View Results** tab.")
                            st.balloons()
                        except Exception as err:
                            st.error(f"Optimizer error: {err}")

        # ──────────────────────────────────────────────
        with tab3:
            st.markdown("### 📊 Allocation Results")
            if not os.path.exists(FINAL_ALLOC_FILE):
                st.info("No allocation available yet. Run the optimizer first.")
            else:
                alloc_view = pd.read_excel(FINAL_ALLOC_FILE)
                rep_sheets = {}
                if os.path.exists(ALLOC_REPORT_FILE):
                    xl = pd.ExcelFile(ALLOC_REPORT_FILE)
                    for sh in xl.sheet_names:
                        rep_sheets[sh] = xl.parse(sh)

                total = len(alloc_view)
                if total > 0 and "Allocated_By" in alloc_view.columns:
                    ab    = alloc_view["Allocated_By"]
                    exact = int((ab=="Willingness-Exact").sum())
                    auto  = int(ab.isin(["Auto-Assigned","OR-Assigned","Gap-Fill"]).sum())
                    pct   = (total - auto) / total * 100
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Total Assignments", total)
                    c2.metric("Exact Willingness", exact)
                    c3.metric("Auto-Assigned", auto)
                    c4.metric("Willingness Match %", f"{pct:.1f}%")

                if "Designation_Summary" in rep_sheets:
                    st.markdown("#### Designation Summary")
                    st.dataframe(rep_sheets["Designation_Summary"],
                                 use_container_width=True, hide_index=True)

                if "Slot_Verification" in rep_sheets:
                    sdf = rep_sheets["Slot_Verification"]
                    unmet = sdf[~sdf["Status"].str.startswith("✓")] if "Status" in sdf.columns else pd.DataFrame()
                    met   = len(sdf) - len(unmet)
                    st.markdown("#### Slot Verification")
                    st.metric("Slots Met", f"{met}/{len(sdf)}",
                              delta="All Met ✓" if len(unmet)==0 else f"{len(unmet)} unmet ⚠")
                    st.dataframe(sdf, use_container_width=True, hide_index=True)

                if "Faculty_Summary" in rep_sheets:
                    st.markdown("#### Faculty Summary")
                    st.dataframe(rep_sheets["Faculty_Summary"],
                                 use_container_width=True, hide_index=True)

                st.markdown("#### Full Allocation Table")
                st.dataframe(alloc_view, use_container_width=True, hide_index=True)

                dl1, dl2 = st.columns(2)
                with dl1:
                    with open(FINAL_ALLOC_FILE,"rb") as fh:
                        st.download_button("⬇ Final_Allocation.xlsx",
                                           data=fh.read(),
                                           file_name="Final_Allocation.xlsx",
                                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                with dl2:
                    with open(ALLOC_REPORT_FILE,"rb") as fh:
                        st.download_button("⬇ Allocation_Report.xlsx",
                                           data=fh.read(),
                                           file_name="Allocation_Report.xlsx",
                                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        st.markdown("")
        if st.button("🔒 Lock Admin View", use_container_width=True, key="lock_admin"):
            st.session_state.admin_authenticated = False
            st.rerun()

    st.markdown("---")
    st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()


# ═══════════════════════════════════════════════════════════════ #
#                        USER VIEW                               #
# ═══════════════════════════════════════════════════════════════ #
st.markdown('<div class="panel-card"><div class="section-title">User View Menu</div></div>',
            unsafe_allow_html=True)
user_panel_mode = st.radio("User View Menu", ["Willingness","Allotment"],
                           horizontal=True, key="user_panel_mode")


# ─────────────────────────────────────────────────────────────── #
#                      ALLOTMENT VIEW                            #
# ─────────────────────────────────────────────────────────────── #
if user_panel_mode == "Allotment":
    st.markdown("### My Allotment Details")
    faculty_names_allot = faculty_df["Name"].dropna().drop_duplicates().tolist()
    sel_name_a = st.selectbox("Select Faculty", faculty_names_allot, key="allotment_faculty_sel")
    sel_clean_a = clean(sel_name_a)

    frow_a_df = faculty_df[faculty_df["Clean"]==sel_clean_a]
    val_display, qp_display = [], []
    if not frow_a_df.empty:
        frow_a = frow_a_df.iloc[0]
        val_display = [f"{format_with_day(d.strftime('%d-%m-%Y'))} - Full Day"
                       for d in valuation_dates_for_faculty(frow_a)]
        qp_display  = [format_with_day(d) for d in collect_qp_feedback_dates(frow_a)]

    w_allot = load_willingness()
    will_display, will_pairs = [], set()
    if not w_allot.empty:
        wm = faculty_match_mask(w_allot, sel_clean_a)
        wr = w_allot[wm]
        if not wr.empty and {"Date","Session"}.issubset(wr.columns):
            for d2, s2 in zip(wr["Date"], wr["Session"]):
                will_display.append(f"{format_with_day(d2)} - {str(s2).strip().upper()}")
                nd = pd.to_datetime(d2, dayfirst=True, errors="coerce")
                if pd.notna(nd): will_pairs.add((nd.date(), str(s2).strip().upper()))

    allot_df = load_final_allotment()
    inv_display, inv_pairs = [], set()
    if not allot_df.empty:
        am = faculty_match_mask(allot_df, sel_clean_a)
        ar = allot_df[am]
        if not ar.empty and {"Date","Session"}.issubset(ar.columns):
            for d2, s2 in zip(ar["Date"], ar["Session"]):
                inv_display.append(f"{format_with_day(d2)} - {str(s2).strip().upper()}")
                nd = pd.to_datetime(d2, dayfirst=True, errors="coerce")
                if pd.notna(nd): inv_pairs.add((nd.date(), str(s2).strip().upper()))
        elif not ar.empty:
            inv_display = ["Allotment record found (date/session columns unavailable)."]

    acc_pct = "Not available"
    if will_pairs:
        matched = len(will_pairs.intersection(inv_pairs))
        acc_pct = f"{(matched/len(will_pairs))*100:.2f}% ({matched}/{len(will_pairs)})"

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="panel-card"><div class="section-title">1) Willingness Options Given</div></div>',
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": will_display or ["Not available"]}),
                     use_container_width=True, hide_index=True)
        st.markdown('<div class="panel-card"><div class="section-title">3) Invigilation Dates (Final Allotment)</div></div>',
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": inv_display or ["Not allotted yet"]}),
                     use_container_width=True, hide_index=True)
    with c2:
        st.markdown('<div class="panel-card"><div class="section-title">2) Valuation Dates (Full Day)</div></div>',
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": val_display or ["Not available"]}),
                     use_container_width=True, hide_index=True)
        st.markdown('<div class="panel-card"><div class="section-title">4) QP Feedback Dates</div></div>',
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": qp_display or ["Not available"]}),
                     use_container_width=True, hide_index=True)

    st.info(f"📊 Willingness accommodated in final allotment: **{acc_pct}**")

    msg_txt = build_delivery_message(sel_name_a, will_display, val_display,
                                     inv_display, qp_display, acc_pct)

    st.markdown('<div class="panel-card"><div class="section-title">📲 Share via WhatsApp</div>'
                '<p class="secure-sub">Enter the WhatsApp number to share allotment summary.</p></div>',
                unsafe_allow_html=True)
    wa_phone = st.text_input("WhatsApp Number (with country code)",
                             placeholder="+919876543210", key="wa_phone_allot")
    if st.button("Generate WhatsApp Link", use_container_width=True, key="gen_wa"):
        if not wa_phone.strip():
            st.warning("Please enter a WhatsApp number.")
        else:
            wa_link = get_whatsapp_link(wa_phone.strip(), msg_txt)
            st.markdown(
                f'<a href="{wa_link}" target="_blank" style="display:inline-block;'
                f'background-color:#25D366;color:white;padding:10px 22px;'
                f'border-radius:10px;font-weight:700;text-decoration:none;font-size:1rem;">'
                f'📲 Open WhatsApp & Send</a>',
                unsafe_allow_html=True,
            )
            st.caption("Opens WhatsApp (web or app) with message pre-filled.")

    with st.expander("Preview Message"):
        st.code(msg_txt, language="text")

    st.markdown("---")
    st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()


# ─────────────────────────────────────────────────────────────── #
#                   WILLINGNESS SUBMISSION                        #
# ─────────────────────────────────────────────────────────────── #
faculty_names = faculty_df["Name"].dropna().drop_duplicates().tolist()
selected_name  = st.selectbox("Select Your Name", faculty_names)
selected_clean = clean(selected_name)
frow_df = faculty_df[faculty_df["Clean"]==selected_clean]
if frow_df.empty:
    st.error("Faculty not found in Faculty_Master.xlsx")
    st.stop()

faculty_row    = frow_df.iloc[0]
designation    = str(faculty_row["Designation"]).strip()
desig_key      = designation.upper()
required_count = DUTY_STRUCTURE.get(desig_key, 0)
if required_count == 0:
    st.warning("Designation not found in DUTY_STRUCTURE. Please verify Faculty_Master.xlsx")

valuation_dates = valuation_dates_for_faculty(faculty_row)
valuation_set   = set(valuation_dates)

offline_opts = offline_df[["Date","Session"]].drop_duplicates().sort_values(["Date","Session"]).copy()
offline_opts["DateOnly"] = offline_opts["Date"].dt.date
online_opts  = online_df[["Date","Session"]].drop_duplicates().sort_values(["Date","Session"]).copy()
online_opts["DateOnly"]  = online_opts["Date"].dt.date

if desig_key == "P":
    sel_opts = online_opts;  sel_label = "Choose Online Date"
else:
    sel_opts = offline_opts; sel_label = "Choose Offline Date"

valid_dates = sorted([d for d in sel_opts["DateOnly"].unique() if d not in valuation_set])

# Reset selections on faculty change
if st.session_state.selected_faculty != selected_clean:
    st.session_state.selected_faculty = selected_clean
    st.session_state.selected_slots   = []
    st.session_state["picked_date"]   = valid_dates[0] if valid_dates else None
if "picked_date" not in st.session_state:
    st.session_state["picked_date"] = valid_dates[0] if valid_dates else None

left, right = st.columns([1, 1.4])

with left:
    st.subheader("Willingness Selection")
    st.write(f"**Designation:** {designation}")
    st.write(f"**Options Required:** {required_count}")

    if desig_key == "ACP":
        st.info(
            "ACP faculty members will receive one online and one offline duty. "
            "Please provide all your willingness using the **offline** calendar. "
            "Online duties will be fixed automatically from your submitted dates."
        )
        st.session_state.acp_notice_shown_for = selected_clean

    if not valid_dates:
        st.warning("No selectable dates available (all blocked by valuation).")
    else:
        picked_date = st.selectbox(
            sel_label, valid_dates, key="picked_date",
            format_func=lambda d: d.strftime("%d-%m-%Y (%A)"),
        )
        avail = set(sel_opts[sel_opts["DateOnly"]==picked_date]["Session"].dropna().astype(str).str.upper())
        b1, b2 = st.columns(2)
        with b1:
            add_fn = st.button("➕ Add FN", use_container_width=True,
                               disabled=("FN" not in avail) or (len(st.session_state.selected_slots)>=required_count))
        with b2:
            add_an = st.button("➕ Add AN", use_container_width=True,
                               disabled=("AN" not in avail) or (len(st.session_state.selected_slots)>=required_count))

        def add_slot(session):
            existing_dates = {item["Date"] for item in st.session_state.selected_slots}
            slot = {"Date": picked_date, "Session": session}
            if picked_date in valuation_set:
                st.warning("Valuation date — cannot select.")
            elif picked_date in existing_dates:
                st.warning("Both FN and AN of the same date are not allowed.")
            elif len(st.session_state.selected_slots) >= required_count:
                st.warning("Required count already reached.")
            elif slot in st.session_state.selected_slots:
                st.warning("Already selected.")
            else:
                st.session_state.selected_slots.append(slot)

        if add_fn: add_slot("FN")
        if add_an: add_slot("AN")

    st.session_state.selected_slots = st.session_state.selected_slots[:required_count]
    st.write(f"**Selected:** {len(st.session_state.selected_slots)} / {required_count}")

    sel_df = pd.DataFrame(st.session_state.selected_slots)
    if not sel_df.empty:
        sel_df = sel_df.sort_values(["Date","Session"]).reset_index(drop=True)
        sel_df.insert(0,"Sl.No", sel_df.index+1)
        sel_df["Day"]  = pd.to_datetime(sel_df["Date"]).dt.day_name()
        sel_df["Date"] = pd.to_datetime(sel_df["Date"]).dt.strftime("%d-%m-%Y")
        st.dataframe(sel_df[["Sl.No","Date","Day","Session"]], use_container_width=True, hide_index=True)

        rm_sl = st.selectbox("Sl.No to remove", options=sel_df["Sl.No"].tolist())
        if st.button("🗑 Remove Selected Row", use_container_width=True):
            target = sel_df[sel_df["Sl.No"]==rm_sl].iloc[0]
            tdate  = pd.to_datetime(target["Date"], dayfirst=True).date()
            tsess  = target["Session"]
            st.session_state.selected_slots = [
                s for s in st.session_state.selected_slots
                if not (s["Date"]==tdate and s["Session"]==tsess)
            ]
            st.rerun()

    # Submission gate
    w_df = load_willingness()
    already_submitted = (
        selected_clean in w_df["FacultyClean"].astype(str).tolist()
        if not w_df.empty and "FacultyClean" in w_df.columns else False
    )

    st.markdown("### Submit Willingness")
    if already_submitted:
        st.warning("⚠ You have already submitted your willingness.")
    remaining = max(required_count - len(st.session_state.selected_slots), 0)
    if already_submitted:
        st.info("Submission already exists for this faculty.")
    elif remaining == 0 and required_count > 0:
        st.success(f"✅ All {required_count} options selected. Ready to submit.")
    else:
        st.info(f"Select {remaining} more option(s) to enable submission.")

    submitted = st.button(
        "✅ Submit Willingness",
        disabled=already_submitted or len(st.session_state.selected_slots)!=required_count,
        use_container_width=True,
    )
    if submitted:
        new_rows = [
            {"Faculty": selected_name,
             "Date": item["Date"].strftime("%d-%m-%Y"),
             "Session": item["Session"]}
            for item in st.session_state.selected_slots
        ]
        out_df = pd.concat(
            [w_df.drop(columns=["FacultyClean"], errors="ignore"),
             pd.DataFrame(new_rows)],
            ignore_index=True,
        )
        out_df.to_excel(WILLINGNESS_FILE, index=False)
        st.toast("Thank you for submitting your willingness! ✅", icon="✅")
        st.success(
            "The University Examination Committee thanks you for submitting your willingness. "
            "The final duty allocation will be carried out using AI-assisted MILP optimization. "
            "Once finalized, the allocation will be officially communicated. "
            "Kindly check this portal regularly for updates."
        )
        st.session_state.selected_slots = []

with right:
    if desig_key == "P":
        render_month_calendars(online_df,  valuation_set, "Online Duty Calendar")
    else:
        render_month_calendars(offline_df, valuation_set, "Offline Duty Calendar")

st.markdown("---")
st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
