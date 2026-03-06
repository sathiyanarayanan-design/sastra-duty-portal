"""
SASTRA SoME End Semester Examination Duty Portal
=================================================
Files required in GitHub repo:
  1. Faculty_Master.xlsx  — faculty list + designation + optional valuation date cols (V1..V5)
  2. Offline_Duty.xlsx    — offline exam slots  (col A: Date | col B: FN/AN | col C: count)
  3. Online_Duty.xlsx     — online exam slots   (col A: Date | col B: FN/AN | col C: count)
  4. sastra_logo.png      — university logo (optional)
  5. Willingness.xlsx     — faculty willingness collected via this portal

Login credentials:
  Faculty portal : SASTRA / SASTRA
  Admin panel    : sathya

v2 improvements:
  1. Slot allocation probability shown live during willingness submission
  2. Admin enable/disable toggle for allotment view (gate file: allotment_gate.txt)
  3. Deviation analysis in allotment page — ADMIN ONLY
"""

import os
import datetime
import warnings
import calendar as calmod
import urllib.parse
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
GATE_FILE         = "allotment_gate.txt"   # "1" = open, "0" = locked

# ─── Designation rules ───────────────────────────────────────── #
DESIG_RULES = {
    "P":   (1, 1, ["Online"]),
    "ACP": (2, 3, ["Online", "Offline"]),
    "SAP": (3, 3, ["Offline"]),
    "AP3": (3, 3, ["Offline"]),
    "AP2": (3, 3, ["Offline"]),
    "TA":  (3, 3, ["Offline"]),
    "RA":  (4, 4, ["Offline"]),
}
DUTY_STRUCTURE = {"P": 3, "ACP": 5, "SAP": 7, "AP3": 7, "AP2": 7, "TA": 9, "RA": 9}

W_EXACT      = 10000
W_ACP_ONLINE =  8000
W_FLIP       =  3000
W_ADJ2       =  1500
W_ADJ        =  2000
W_NON_SUB    =    10
PENALTY      =     1

WILL_TAGS = {
    "Willingness-Exact", "Willingness-ACPOnline",
    "Willingness-SessionFlip", "Willingness-±1Day", "Willingness-±2Day"
}

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
#              ALLOTMENT GATE  (Feature 2)                       #
# ═══════════════════════════════════════════════════════════════ #
def gate_is_open() -> bool:
    try:
        with open(GATE_FILE) as f:
            return f.read().strip() == "1"
    except FileNotFoundError:
        return False

def set_gate(open_: bool):
    with open(GATE_FILE, "w") as f:
        f.write("1" if open_ else "0")


# ═══════════════════════════════════════════════════════════════ #
#                     UTILITY FUNCTIONS                          #
# ═══════════════════════════════════════════════════════════════ #
def clean(x):
    return str(x).strip().lower()

def normalize_session(v):
    t = str(v).strip().upper()
    if t in {"FN", "FORENOON", "MORNING", "AM"}:
        return "FN"
    if t in {"AN", "AFTERNOON", "EVENING", "PM"}:
        return "AN"
    return t

def fmt_day(val):
    dt = pd.to_datetime(val, dayfirst=True, errors="coerce")
    return f"{dt.strftime('%d-%m-%Y')} ({dt.strftime('%A')})" if pd.notna(dt) else str(val)

def valuation_dates_for(row):
    return sorted({
        pd.to_datetime(row[c], dayfirst=True).date()
        for c in ["V1", "V2", "V3", "V4", "V5"]
        if c in row.index and pd.notna(row[c])
    })

def qp_dates_for(row):
    return sorted({
        pd.to_datetime(row[c], dayfirst=True, errors="coerce").strftime("%d-%m-%Y")
        for c in row.index
        if "QP" in str(c).upper()
        and "DATE" in str(c).upper()
        and pd.notna(row[c])
        and pd.notna(pd.to_datetime(row[c], dayfirst=True, errors="coerce"))
    })

def fac_mask(df, sel_clean):
    if df.empty:
        return pd.Series([], dtype=bool)
    cols = [c for c in df.columns if "name" in c.lower() or "faculty" in c.lower()]
    mask = pd.Series([False] * len(df), index=df.index)
    for c in cols:
        mask = mask | (df[c].astype(str).apply(clean) == sel_clean)
    return mask

def wa_link(phone, msg):
    p = str(phone).strip().replace("+", "").replace(" ", "").replace("-", "")
    return f"https://wa.me/{p}?text={urllib.parse.quote(msg)}"

def build_msg(name, will, val, inv, qp, match_str="", dev_lines=None):
    lines = [
        f"Dear {name},", "",
        "Examination Duty Details:", "",
        "1) Invigilation Dates (Final Allotment):",
        *(inv or ["Not allotted yet"]), "",
        "2) Valuation Dates (Full Day):",
        *(val or ["Not available"]), "",
        "3) QP Feedback Dates:",
        *(qp or ["Not available"]), "",
    ]
    if match_str:
        lines += [
            "4) Willingness Match Summary:",
            f"   {match_str}",
            *(dev_lines or []), "",
        ]
    lines.append("- SASTRA SoME Examination Committee")
    return "\n".join(lines)

def render_header(logo=True):
    if logo and os.path.exists(LOGO_FILE):
        _, c2, _ = st.columns([2, 1, 2])
        with c2:
            st.image(LOGO_FILE, width=180)
    st.markdown(
        "<h2 style='text-align:center;margin-bottom:.25rem'>"
        "SASTRA SoME End Semester Examination Duty Portal</h2>",
        unsafe_allow_html=True
    )
    st.markdown(
        "<h4 style='text-align:center;margin-top:0'>"
        "School of Mechanical Engineering</h4>",
        unsafe_allow_html=True
    )
    st.markdown("---")


# ═══════════════════════════════════════════════════════════════ #
#               PARSE DUTY FILE (shared helper)                  #
# ═══════════════════════════════════════════════════════════════ #
def parse_duty_file(filepath, duty_type):
    if not os.path.exists(filepath):
        return []
    try:
        raw = pd.read_excel(filepath, header=None)
    except Exception:
        return []
    try:
        pd.to_datetime(raw.iloc[0, 0])
        start = 0
    except Exception:
        start = 1
    slots = []
    for i in range(start, len(raw)):
        row = raw.iloc[i]
        d    = row.iloc[0]
        sess = row.iloc[1] if len(row) > 1 else None
        req  = row.iloc[2] if len(row) > 2 else 1
        if pd.isna(d):
            continue
        sn = normalize_session(sess)
        if sn not in ("FN", "AN"):
            continue
        try:
            date = pd.to_datetime(d).date()
        except Exception:
            continue
        try:
            required = max(int(float(req)), 0)
        except Exception:
            required = 1
        slots.append({"date": date, "session": sn, "required": required, "type": duty_type})
    return slots

@st.cache_data
def load_slots(off_path, on_path):
    def to_df(slots):
        if not slots:
            df = pd.DataFrame(columns=["Date", "Session", "Required"])
            df["Date"] = pd.to_datetime(df["Date"])
            return df
        df = pd.DataFrame(slots)
        df["Date"]     = pd.to_datetime(df["date"], errors="coerce")
        df["Session"]  = df["session"]
        df["Required"] = df["required"].astype(int)
        return df[["Date", "Session", "Required"]]
    return to_df(parse_duty_file(off_path, "Offline")), to_df(parse_duty_file(on_path, "Online"))


# ═══════════════════════════════════════════════════════════════ #
#               WILLINGNESS FILE FUNCTIONS                       #
# ═══════════════════════════════════════════════════════════════ #
def load_willingness():
    if not os.path.exists(WILLINGNESS_FILE):
        return pd.DataFrame(columns=["Faculty", "Date", "Session", "FacultyClean"])
    try:
        xl = pd.ExcelFile(WILLINGNESS_FILE)
        df = None
        for sh in xl.sheet_names:
            c = xl.parse(sh)
            c.columns = c.columns.str.strip()
            if {"Faculty", "Date", "Session"}.issubset(set(c.columns)):
                df = c[["Faculty", "Date", "Session"]].copy()
                break
        if df is None:
            c = xl.parse(xl.sheet_names[0])
            c.columns = c.columns.str.strip()
            if len(c.columns) >= 3:
                c = c.rename(columns={c.columns[0]: "Faculty", c.columns[1]: "Date", c.columns[2]: "Session"})
                df = c[["Faculty", "Date", "Session"]].copy()
            else:
                df = pd.DataFrame(columns=["Faculty", "Date", "Session"])
    except Exception:
        df = pd.DataFrame(columns=["Faculty", "Date", "Session"])

    df["Faculty"]      = df["Faculty"].astype(str).str.strip()
    df["Date"]         = df["Date"].astype(str).str.strip()
    df["Session"]      = df["Session"].astype(str).str.strip().str.upper()
    df["FacultyClean"] = df["Faculty"].apply(clean)
    return df.dropna(subset=["Faculty"]).reset_index(drop=True)

def get_all_willingness():
    committed = load_willingness().drop(columns=["FacultyClean"], errors="ignore")
    pending   = st.session_state.get(
        "pending_submissions", pd.DataFrame(columns=["Faculty", "Date", "Session"]))
    combined  = pd.concat([committed, pending], ignore_index=True)
    combined  = combined.drop_duplicates(subset=["Faculty", "Date", "Session"])
    combined["FacultyClean"] = combined["Faculty"].apply(clean)
    return combined

def save_submission(faculty_name, slots):
    new_rows = pd.DataFrame([
        {"Faculty": faculty_name,
         "Date": item["Date"].strftime("%d-%m-%Y"),
         "Session": item["Session"]}
        for item in slots
    ])
    if "pending_submissions" not in st.session_state:
        st.session_state.pending_submissions = pd.DataFrame(columns=["Faculty", "Date", "Session"])
    st.session_state.pending_submissions = pd.concat(
        [st.session_state.pending_submissions, new_rows], ignore_index=True)


# ═══════════════════════════════════════════════════════════════ #
#        FEATURE 1 — SLOT PROBABILITY INDICATOR                  #
# ═══════════════════════════════════════════════════════════════ #
def slot_probability(all_will_df, duty_df, date_val, session_val):
    seats = 0
    if not duty_df.empty:
        m = duty_df[
            (duty_df["Date"].dt.date == date_val) &
            (duty_df["Session"].str.upper() == session_val.upper())
        ]
        if not m.empty:
            seats = int(m["Required"].sum())

    applicants = 0
    if not all_will_df.empty and "Date" in all_will_df.columns:
        norm = pd.to_datetime(all_will_df["Date"], dayfirst=True, errors="coerce")
        applicants = int((
            (norm.dt.date == date_val) &
            (all_will_df["Session"].str.upper() == session_val.upper())
        ).sum())

    if seats == 0:
        prob, label, colour = 0.0, "No slot on this day", "#94a3b8"
    elif applicants == 0:
        prob, label, colour = 100.0, "High — you'd be first!", "#16a34a"
    else:
        prob = min(seats / applicants, 1.0) * 100
        if prob >= 70:
            prob, label, colour = prob, "High", "#16a34a"
        elif prob >= 40:
            prob, label, colour = prob, "Medium", "#f59e0b"
        else:
            prob, label, colour = prob, "Low — many applicants", "#dc2626"

    return {"seats": seats, "applicants": applicants,
            "probability": prob, "label": label, "colour": colour}

def render_prob_bar(info: dict, session_label: str):
    pct    = info["probability"]
    colour = info["colour"]
    w      = f"{pct:.0f}%"
    st.markdown(f"""
<div style="background:#fff;border:1px solid #e2e8f0;border-radius:10px;
            padding:10px 14px;margin-bottom:8px;">
  <div style="font-weight:700;font-size:.95rem;color:#0f172a;margin-bottom:4px;">
    {session_label} &nbsp;·&nbsp;
    <span style="color:{colour}">{pct:.0f}% allocation probability</span>
  </div>
  <div style="background:#e5e7eb;border-radius:6px;height:12px;width:100%;margin:4px 0">
    <div style="background:{colour};border-radius:6px;height:12px;width:{w}"></div>
  </div>
  <div style="font-size:.82rem;color:#475569;margin-top:3px;">
    🎯 Seats: <b>{info['seats']}</b> &nbsp;|&nbsp;
    👥 Applied so far: <b>{info['applicants']}</b> &nbsp;|&nbsp;
    {info['label']}
  </div>
</div>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════ #
#        DEVIATION ANALYSIS  (admin-only helper)                 #
# ═══════════════════════════════════════════════════════════════ #
def classify_duty(alloc_by: str, duty_date, duty_sess: str, will_set: set):
    ab = str(alloc_by).strip()

    if ab == "Willingness-Exact":
        return ("Exact Match", "✅",
                "Allotted on your exact submitted date & session", True)

    if ab == "Willingness-ACPOnline":
        return ("Session Adjusted", "🔄",
                "Your offline-date willingness was used to fill your online duty slot", True)

    if ab == "Willingness-SessionFlip":
        opp = "AN" if duty_sess == "FN" else "FN"
        return ("Session Adjusted", "🔄",
                f"You submitted {duty_date.strftime('%d-%m-%Y')} {opp} → allotted {duty_sess} "
                f"(same date, session swapped)", True)

    if ab in ("Willingness-±1Day", "Willingness-±2Day"):
        window = "±1 day" if "1Day" in ab else "±2 days"
        closest = ""
        deltas  = [-1, 1] if "1Day" in ab else [-2, -1, 1, 2]
        for delta in deltas:
            adj = duty_date + datetime.timedelta(days=delta)
            for s in ["FN", "AN"]:
                if (adj, s) in will_set:
                    direction = "after" if delta > 0 else "before"
                    closest = (f"You submitted {adj.strftime('%d-%m-%Y')} {s} "
                                f"→ duty shifted {abs(delta)} day(s) {direction} "
                                f"to {duty_date.strftime('%d-%m-%Y')} {duty_sess}")
                    break
            if closest:
                break
        return (f"Date Adjusted ({window})", "📅",
                closest or f"Allotted within {window} of your submitted willingness", True)

    if ab in ("Auto-Assigned", "Gap-Fill"):
        return ("Auto-Assigned", "⚙️",
                "No willingness submitted — system assigned this duty to meet slot requirements",
                False)

    return ("Not in Willingness", "🔴",
            f"No willingness found near {duty_date.strftime('%d-%m-%Y')} {duty_sess} "
            f"— system assigned to meet slot requirements", False)


def render_deviation_section(allot_rows: pd.DataFrame, will_set: set):
    """Admin-only: full deviation analysis with metrics, per-duty table, and summary."""
    if allot_rows.empty:
        st.info("No allotment data found for this faculty yet.")
        return "Not available", []

    duty_rows = []
    for _, ar in allot_rows.iterrows():
        norm = pd.to_datetime(ar["Date"], dayfirst=True, errors="coerce")
        if pd.isna(norm):
            continue
        sess     = str(ar.get("Session", "")).strip().upper()
        dtype    = str(ar.get("Type", "")).strip()
        alloc_by = str(ar.get("Allocated_By", "")).strip()
        status, emoji, detail, is_matched = classify_duty(
            alloc_by, norm.date(), sess, will_set)
        duty_rows.append({
            "norm_date":  norm.date(),
            "sess":       sess,
            "dtype":      dtype,
            "status":     status,
            "emoji":      emoji,
            "detail":     detail,
            "is_matched": is_matched,
            "date_fmt":   fmt_day(norm.strftime("%d-%m-%Y")),
        })

    total     = len(duty_rows)
    n_exact   = sum(1 for d in duty_rows if d["status"] == "Exact Match")
    n_sess    = sum(1 for d in duty_rows if d["status"] == "Session Adjusted")
    n_adj     = sum(1 for d in duty_rows if "Date Adjusted" in d["status"])
    n_no      = sum(1 for d in duty_rows if not d["is_matched"])
    n_matched = n_exact + n_sess + n_adj

    match_pct = n_matched / total * 100 if total else 0.0
    dev_pct   = 100.0 - match_pct

    allot_set    = {(d["norm_date"], d["sess"]) for d in duty_rows}
    exact_overlap = len(will_set & allot_set)
    will_used_pct = exact_overlap / len(will_set) * 100 if will_set else 0.0

    st.markdown("---")
    st.markdown("### 📊 Willingness Match & Deviation")

    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Duties Allotted", total)
    with m2:
        st.metric("Willingness Match", f"{match_pct:.1f}%",
                  delta=f"{n_matched} of {total} within window")
    with m3:
        st.metric("Deviation", f"{dev_pct:.1f}%",
                  delta=f"{n_no} unmatched" if n_no else "None",
                  delta_color="inverse" if n_no else "off")
    with m4:
        st.metric("Your Exact Slots Used", f"{will_used_pct:.1f}%",
                  help=f"{exact_overlap} of your {len(will_set)} submitted slots allotted exactly")

    if total == 0:
        return "Not available", []
    elif dev_pct == 0.0:
        st.success("🎉 All duties were allotted exactly as per submitted willingness!")
    elif n_no == 0:
        st.info(
            f"ℹ️ All {total} duties fall within the willingness window. "
            f"{n_sess + n_adj} minor adjustment(s) were made "
            f"(session swap or date shift of ±1/±2 days)."
        )
    else:
        st.warning(
            f"⚠️ {n_no} of {total} duties could not be matched to any submitted willingness "
            "and were system-assigned to meet examination slot requirements."
        )

    st.markdown("#### Duty-wise Breakdown")

    STATUS_BG = {
        "Exact Match":            ("#d1fae5", "#065f46"),
        "Session Adjusted":       ("#fef3c7", "#92400e"),
        "Date Adjusted (±1 day)": ("#ffedd5", "#9a3412"),
        "Date Adjusted (±2 days)":("#ffedd5", "#9a3412"),
        "Not in Willingness":     ("#fee2e2", "#991b1b"),
        "Auto-Assigned":          ("#e5e7eb", "#374151"),
    }

    rows_html = ""
    for d in duty_rows:
        bg, fg = STATUS_BG.get(d["status"], ("#e5e7eb", "#374151"))
        rows_html += f"""
<tr>
  <td style="padding:7px 10px;font-size:.87rem;">{d['date_fmt']}</td>
  <td style="padding:7px 10px;text-align:center;font-weight:700">{d['sess']}</td>
  <td style="padding:7px 10px;text-align:center;">{d['dtype']}</td>
  <td style="padding:7px 10px;">
    <span style="display:inline-block;padding:2px 10px;border-radius:12px;
                 font-size:.8rem;font-weight:700;background:{bg};color:{fg};">
      {d['emoji']} {d['status']}
    </span>
  </td>
  <td style="padding:7px 10px;font-size:.82rem;color:#475569;">{d['detail']}</td>
</tr>"""

    st.markdown(f"""
<div style="overflow-x:auto">
<table style="width:100%;border-collapse:collapse;background:#fff;
              border-radius:10px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,.06)">
  <thead>
    <tr style="background:#f1f5f9;font-size:.85rem;font-weight:700;color:#0f172a;">
      <th style="padding:8px 10px;text-align:left">Allotted Date</th>
      <th style="padding:8px 10px;text-align:center">Session</th>
      <th style="padding:8px 10px;text-align:center">Type</th>
      <th style="padding:8px 10px;text-align:left">Match Status</th>
      <th style="padding:8px 10px;text-align:left">Detail</th>
    </tr>
  </thead>
  <tbody>{rows_html}</tbody>
</table>
</div>
""", unsafe_allow_html=True)

    st.markdown("#### Summary by Category")
    bd = pd.DataFrame({
        "Category": [
            "✅ Exact Match",
            "🔄 Session Adjusted (FN↔AN, same date)",
            "📅 Date Adjusted (±1 or ±2 days)",
            "🔴 Not in Willingness / Auto-Assigned",
        ],
        "Count": [n_exact, n_sess, n_adj, n_no],
        "Share %": [
            f"{n_exact/total*100:.1f}%" if total else "—",
            f"{n_sess/total*100:.1f}%"  if total else "—",
            f"{n_adj/total*100:.1f}%"   if total else "—",
            f"{n_no/total*100:.1f}%"    if total else "—",
        ],
        "Meaning": [
            "Allotted on the exact date & session you submitted",
            "Same date, but morning/afternoon slot was swapped",
            "Duty shifted 1 or 2 days from your submitted date",
            "No matching date — system assigned to fill slot",
        ],
    })
    st.dataframe(bd, use_container_width=True, hide_index=True)

    dev_lines = [f"Overall match: {match_pct:.1f}%  ({n_matched}/{total} duties within willingness window)"]
    if n_no == 0 and dev_pct == 0:
        dev_lines.append("All duties allotted exactly as per your willingness.")
    else:
        if n_exact > 0:
            dev_lines.append(f"  ✅ Exact match      : {n_exact} duty(ies)")
        if n_sess > 0:
            dev_lines.append(f"  🔄 Session swapped  : {n_sess} duty(ies) (FN↔AN, same date)")
        if n_adj > 0:
            dev_lines.append(f"  📅 Date shifted     : {n_adj} duty(ies) (±1 or ±2 days)")
        if n_no > 0:
            dev_lines.append(f"  🔴 System-assigned  : {n_no} duty(ies) (outside willingness window)")

    match_str = f"Match {match_pct:.1f}%  ({n_matched}/{total})  |  Deviation {dev_pct:.1f}%"
    return match_str, dev_lines


# ═══════════════════════════════════════════════════════════════ #
#                    CALENDAR HEATMAP                            #
# ═══════════════════════════════════════════════════════════════ #
def demand_cat(r):
    if r == 0:   return "No Duty"
    if r < 3:    return "Low (<3)"
    if r <= 7:   return "Medium (3-7)"
    return "High (>7)"

def calendar_frame(duty_df, val_dates, year, month):
    sg   = duty_df.groupby(["Date", "Session"], as_index=False)["Required"].sum()
    dmap = {(d.date(), s): int(r) for d, s, r in zip(sg["Date"], sg["Session"], sg["Required"])}
    ms   = pd.Timestamp(year=year, month=month, day=1)
    fw   = ms.weekday()
    WD   = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    rows = []
    for dt in pd.date_range(ms, ms + pd.offsets.MonthEnd(0), freq="D"):
        wk = ((dt.day + fw - 1) // 7) + 1
        do = dt.date()
        for sess in ["FN", "AN"]:
            req = dmap.get((do, sess), 0)
            cat = "Valuation Locked" if do in val_dates else demand_cat(req)
            rows.append({"Date": dt, "Week": wk, "Weekday": WD[dt.weekday()],
                         "DayNum": dt.day, "Session": sess, "Required": req,
                         "Category": cat, "DateLabel": dt.strftime("%d-%m-%Y")})
    return pd.DataFrame(rows)

def render_calendar(duty_df, val_dates, title):
    st.markdown(f"#### {title}")
    if duty_df.empty:
        st.info("No slot data available.")
        return
    months = sorted({(d.year, d.month) for d in duty_df["Date"]})
    cscale = alt.Scale(
        domain=["No Duty", "Low (<3)", "Medium (3-7)", "High (>7)", "Valuation Locked"],
        range=["#ececec", "#2ca02c", "#f1c40f", "#d62728", "#ff69b4"]
    )
    st.markdown(
        "**Legend:** ⬜ No Duty &nbsp;🟩 Low (<3) &nbsp;🟨 Medium (3-7) "
        "&nbsp;🟥 High (>7) &nbsp;🩷 Valuation Locked"
    )
    for yr, mo in months:
        frame = calendar_frame(duty_df, set(val_dates), yr, mo)
        st.markdown(f"**{calmod.month_name[mo]} {yr}**")
        base = alt.Chart(frame).encode(
            x=alt.X("Weekday:N", sort=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], title=""),
            xOffset=alt.XOffset("Session:N", sort=["FN", "AN"]),
            y=alt.Y("Week:O", sort="ascending", title=""),
            tooltip=[alt.Tooltip("DateLabel:N", title="Date"),
                     alt.Tooltip("Session:N",   title="Session"),
                     alt.Tooltip("Required:Q",  title="Demand"),
                     alt.Tooltip("Category:N",  title="Category")]
        )
        rect = base.mark_rect(stroke="white").encode(
            color=alt.Color("Category:N", scale=cscale, legend=alt.Legend(title="Legend")))
        day_text = (
            alt.Chart(frame[frame["Session"] == "FN"])
            .mark_text(color="black", fontSize=11, dy=-6)
            .encode(
                x=alt.X("Weekday:N", sort=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
                y=alt.Y("Week:O", sort="ascending"),
                text=alt.Text("DayNum:Q"))
        )
        st.altair_chart((rect + day_text).properties(height=230), use_container_width=True)
        st.caption("Left half = FN  |  Right half = AN")


# ═══════════════════════════════════════════════════════════════ #
#              MILP OPTIMIZER  (HiGHS via scipy)                 #
# ═══════════════════════════════════════════════════════════════ #
def run_optimizer(log_box):
    log_lines = []
    def log(m=""):
        log_lines.append(m)
        log_box.code("\n".join(log_lines), language="text")

    log("=" * 62)
    log("  SASTRA SoME Duty Optimizer  (HiGHS MILP  –  v2 High-Match)")
    log("=" * 62)

    fr = pd.read_excel(FACULTY_FILE)
    fr.columns = fr.columns.str.strip()
    col_names = fr.columns.tolist()
    if len(col_names) < 2:
        raise RuntimeError("Faculty_Master.xlsx must have at least 2 columns: Name and Designation.")
    fr.rename(columns={col_names[0]: "Name", col_names[1]: "Designation"}, inplace=True)
    fr = fr.dropna(subset=["Name"]).reset_index(drop=True)
    fr["Name"]        = fr["Name"].astype(str).str.strip()
    fr["Designation"] = fr["Designation"].astype(str).str.strip().str.upper()

    ALL_FAC = fr["Name"].tolist()
    FAC_IDX = {n: i for i, n in enumerate(ALL_FAC)}
    N_FAC   = len(ALL_FAC)
    fac_d   = {row["Name"]: (row["Designation"] if row["Designation"] in DESIG_RULES else "TA")
               for _, row in fr.iterrows()}
    dgroups = defaultdict(list)
    for n, d in fac_d.items(): dgroups[d].append(n)
    log(f"\n  Faculty loaded     : {N_FAC}")

    wdf = get_all_willingness().drop(columns=["FacultyClean"], errors="ignore")
    if not wdf.empty:
        wdf["Date"]    = pd.to_datetime(wdf["Date"], dayfirst=True, errors="coerce")
        wdf["Session"] = wdf["Session"].astype(str).str.strip().str.upper()
        wdf = wdf.dropna(subset=["Date"])

    submitted = set(wdf["Faculty"].str.strip().unique()) if not wdf.empty else set()
    non_sub   = [n for n in ALL_FAC if n not in submitted]
    log(f"  Willingness loaded : {len(submitted)} submitted  |  {len(non_sub)} not submitted")

    log("")
    for fp, dt_label in [(OFFLINE_FILE, "Offline"), (ONLINE_FILE, "Online")]:
        log(f"  {dt_label:8} file : {'✓ ' + fp if os.path.exists(fp) else '✗ MISSING — ' + fp}")

    s_off = parse_duty_file(OFFLINE_FILE, "Offline")
    s_on  = parse_duty_file(ONLINE_FILE,  "Online")
    ALL_S = s_off + s_on
    NS    = len(ALL_S)
    log(f"  Slots parsed       : {NS}  ({len(s_off)} offline + {len(s_on)} online)")
    if NS == 0:
        raise RuntimeError("No exam slots found. Check Offline_Duty.xlsx / Online_Duty.xlsx.")
    total_needed = sum(s["required"] for s in ALL_S)
    log(f"  Total assignments  : {total_needed}")

    fexp = defaultdict(dict)
    def set_score(d, k, val): d[k] = max(d.get(k, 0), val)

    for _, row in wdf.iterrows():
        n       = str(row.get("Faculty", "")).strip()
        if n not in FAC_IDX: continue
        dt2     = row["Date"].date()
        sess    = str(row["Session"]).strip().upper()
        allowed = DESIG_RULES[fac_d.get(n, "TA")][2]

        for tp in allowed:
            set_score(fexp[n], (dt2, sess, tp), W_EXACT)
        if fac_d.get(n) == "ACP":
            for s2 in ["FN", "AN"]:
                set_score(fexp[n], (dt2, s2, "Online"), W_ACP_ONLINE)
        opp = "AN" if sess == "FN" else "FN"
        for tp in allowed:
            set_score(fexp[n], (dt2, opp, tp), W_FLIP)
        for delta in [-1, +1]:
            adj = dt2 + datetime.timedelta(days=delta)
            for s2 in ["FN", "AN"]:
                for tp in allowed:
                    set_score(fexp[n], (adj, s2, tp), W_ADJ)
        for delta in [-2, +2]:
            adj = dt2 + datetime.timedelta(days=delta)
            for s2 in ["FN", "AN"]:
                for tp in allowed:
                    set_score(fexp[n], (adj, s2, tp), W_ADJ2)

    for n in non_sub:
        allowed = DESIG_RULES[fac_d.get(n, "TA")][2]
        for s in ALL_S:
            if s["type"] in allowed:
                k = (s["date"], s["session"], s["type"])
                set_score(fexp[n], k, W_NON_SUB)

    def v(fi, si): return fi * NS + si
    NV    = N_FAC * NS
    c_obj = np.zeros(NV)
    lb    = np.zeros(NV)
    ub    = np.ones(NV)

    for fi, fn in enumerate(ALL_FAC):
        allowed = DESIG_RULES[fac_d[fn]][2]
        for si, sl in enumerate(ALL_S):
            if sl["type"] not in allowed:
                ub[v(fi, si)] = 0.0
                continue
            k  = (sl["date"], sl["session"], sl["type"])
            sc = fexp[fn].get(k, 0)
            if sc > 0:
                c_obj[v(fi, si)] = -float(sc)
            elif fn in submitted:
                c_obj[v(fi, si)] = float(PENALTY)

    rA, cA, dA, blo, bhi = [], [], [], [], []
    nc = [0]
    def add_con(var_ids, coeffs, lo, hi):
        for vi, co in zip(var_ids, coeffs):
            rA.append(nc[0]); cA.append(vi); dA.append(float(co))
        blo.append(float(lo)); bhi.append(float(hi)); nc[0] += 1

    on_i  = [i for i, s in enumerate(ALL_S) if s["type"] == "Online"]
    off_i = [i for i, s in enumerate(ALL_S) if s["type"] == "Offline"]

    for si, sl in enumerate(ALL_S):
        add_con([v(f, si) for f in range(N_FAC)], [1] * N_FAC, sl["required"], sl["required"])
    for fi, fn in enumerate(ALL_FAC):
        dr = DESIG_RULES[fac_d[fn]]
        add_con([v(fi, s) for s in range(NS)], [1] * NS, dr[0], dr[1])
    dt_tp = defaultdict(list)
    for si, sl in enumerate(ALL_S): dt_tp[(sl["date"], sl["type"])].append(si)
    for fi in range(N_FAC):
        for sil in dt_tp.values():
            if len(sil) > 1:
                add_con([v(fi, si) for si in sil], [1] * len(sil), 0, 1)
    for fn in dgroups["P"]:
        fi = FAC_IDX[fn]
        if on_i: add_con([v(fi, si) for si in on_i], [1] * len(on_i), 1, 1)
    for fn in dgroups["ACP"]:
        fi = FAC_IDX[fn]
        if on_i:  add_con([v(fi, si) for si in on_i],  [1] * len(on_i),  1, len(on_i))
        if off_i: add_con([v(fi, si) for si in off_i], [1] * len(off_i), 1, len(off_i))

    WILL_FLOOR = 0.80
    forced_count = 0
    for fn in submitted:
        fi = FAC_IDX.get(fn)
        if fi is None: continue
        dr    = DESIG_RULES[fac_d[fn]]
        w_si  = [si for si in range(NS)
                 if fexp[fn].get((ALL_S[si]["date"], ALL_S[si]["session"], ALL_S[si]["type"]), 0) >= W_ADJ2
                 and ub[v(fi, si)] > 0]
        if not w_si: continue
        floor_val = min(max(1, int(np.floor(dr[0] * WILL_FLOOR))), len(w_si))
        add_con([v(fi, si) for si in w_si], [1] * len(w_si), floor_val, len(w_si))
        forced_count += 1
    log(f"  Willingness floor constraints added : {forced_count} faculty")

    A = csc_matrix((dA, (rA, cA)), shape=(nc[0], NV))
    log(f"\n  Variables    : {NV}  |  Constraints : {nc[0]}")
    log("  Solving HiGHS MILP (time limit 300 s)...")
    res = milp(c=c_obj, constraints=LinearConstraint(A, blo, bhi),
               integrality=np.ones(NV), bounds=Bounds(lb=lb, ub=ub),
               options={"disp": False, "time_limit": 300})
    log(f"  Status : {res.message}")

    def tag(fn, k, sc):
        if fn in non_sub:       return "Auto-Assigned"
        if sc >= W_EXACT:       return "Willingness-Exact"
        if sc >= W_ACP_ONLINE:  return "Willingness-ACPOnline"
        if sc >= W_FLIP:        return "Willingness-SessionFlip"
        if sc >= W_ADJ:         return "Willingness-±1Day"
        if sc >= W_ADJ2:        return "Willingness-±2Day"
        return "OR-Assigned"

    assigned = []
    if res.status in (0, 1):
        x = np.round(res.x).astype(int)
        for fi, fn in enumerate(ALL_FAC):
            for si, sl in enumerate(ALL_S):
                if x[v(fi, si)] == 1:
                    k  = (sl["date"], sl["session"], sl["type"])
                    sc = fexp[fn].get(k, 0)
                    assigned.append({"Name": fn, "Date": sl["date"], "Session": sl["session"],
                                     "Type": sl["type"], "Allocated_By": tag(fn, k, sc)})
        method = "MILP Optimal (HiGHS)"
    else:
        log("  ⚠ MILP infeasible — greedy fallback...")
        method = "Greedy Fallback"
        alloc_count = defaultdict(int); used_dt = defaultdict(set)
        def remaining(n): return DESIG_RULES[fac_d[n]][0] - alloc_count[n]
        def ok(n, dt_, tp_):
            return tp_ in DESIG_RULES[fac_d[n]][2] and (dt_, tp_) not in used_dt[n] and remaining(n) > 0
        for sl in sorted(ALL_S, key=lambda s: -s["required"]):
            d2, s2, r2, t2 = sl["date"], sl["session"], sl["required"], sl["type"]
            k = (d2, s2, t2)
            candidates = sorted(
                [(n, fexp[n].get(k, 0)) for n in ALL_FAC if ok(n, d2, t2)],
                key=lambda x: (-x[1], alloc_count[x[0]]))
            for fn, sc in candidates[:r2]:
                alloc_count[fn] += 1; used_dt[fn].add((d2, t2))
                assigned.append({"Name": fn, "Date": d2, "Session": s2,
                                  "Type": t2, "Allocated_By": tag(fn, k, sc)})
        for fn in ALL_FAC:
            if remaining(fn) <= 0: continue
            for sl in sorted(ALL_S, key=lambda s: s["date"]):
                if remaining(fn) <= 0: break
                d2, s2, t2 = sl["date"], sl["session"], sl["type"]
                if not ok(fn, d2, t2): continue
                alloc_count[fn] += 1; used_dt[fn].add((d2, t2))
                assigned.append({"Name": fn, "Date": d2, "Session": s2,
                                  "Type": t2, "Allocated_By": "Gap-Fill"})

    alloc = pd.DataFrame(assigned)
    if alloc.empty:
        raise RuntimeError("No assignments produced. Check input files.")
    alloc["Date"] = pd.to_datetime(alloc["Date"]).dt.strftime("%d-%m-%Y")
    alloc = alloc.sort_values(["Date", "Session", "Name"]).reset_index(drop=True)
    alloc.insert(0, "Sl.No", alloc.index + 1)

    sumrows = []
    for fn in ALL_FAC:
        d2 = fac_d[fn]; dr = DESIG_RULES[d2]
        rf = alloc[alloc["Name"] == fn]; ab = rf["Allocated_By"]
        total_assigned = len(rf)
        will_total = int(ab.isin(WILL_TAGS).sum())
        match_pct  = f"{will_total / total_assigned * 100:.0f}%" if total_assigned > 0 else "N/A"
        sumrows.append({
            "Name": fn, "Designation": d2,
            "Submitted": "Yes" if fn in submitted else "No",
            "Required_Duties": dr[0], "Assigned_Duties": total_assigned,
            "Willingness_Total": will_total, "Match_%": match_pct,
            "Exact_Match":   int((ab == "Willingness-Exact").sum()),
            "ACP_Online":    int((ab == "Willingness-ACPOnline").sum()),
            "Session_Flip":  int((ab == "Willingness-SessionFlip").sum()),
            "Adj_±1Day":     int((ab == "Willingness-±1Day").sum()),
            "Adj_±2Day":     int((ab == "Willingness-±2Day").sum()),
            "Auto_Assigned": int(ab.isin(["Auto-Assigned", "OR-Assigned", "Gap-Fill"]).sum()),
            "Online":  int((rf["Type"] == "Online").sum()),
            "Offline": int((rf["Type"] == "Offline").sum()),
            "Gap": max(dr[0] - len(rf), 0)
        })
    sumdf = pd.DataFrame(sumrows)

    slotrows = []
    for sl in ALL_S:
        ds = pd.Timestamp(sl["date"]).strftime("%d-%m-%Y")
        na = len(alloc[(alloc["Date"] == ds) & (alloc["Session"] == sl["session"])
                       & (alloc["Type"] == sl["type"])])
        slotrows.append({"Date": ds, "Session": sl["session"], "Type": sl["type"],
                         "Required": sl["required"], "Assigned": na,
                         "Status": "✓" if na >= sl["required"] else f"✗ short {sl['required'] - na}"})
    slotdf = pd.DataFrame(slotrows)

    desigrows = []
    for d2 in DESIG_RULES:
        sub2 = sumdf[sumdf["Designation"] == d2]
        if sub2.empty: continue
        on = int(sub2["Online"].sum()); of = int(sub2["Offline"].sum())
        dr = DESIG_RULES[d2]
        desigrows.append({"Designation": d2, "Faculty_Count": len(sub2),
                          "Duties_Per_Person": dr[0], "Total_Required": dr[0] * len(sub2),
                          "Total_Assigned": on + of,
                          "Willingness_Matched": int(sub2["Willingness_Total"].sum()),
                          "Auto_Assigned": int(sub2["Auto_Assigned"].sum()),
                          "Online": on, "Offline": of})
    desigdf = pd.DataFrame(desigrows)

    alloc.to_excel(FINAL_ALLOC_FILE, index=False)
    with pd.ExcelWriter(ALLOC_REPORT_FILE, engine="openpyxl") as writer:
        desigdf.to_excel(writer, sheet_name="Designation_Summary", index=False)
        sumdf.to_excel(writer,   sheet_name="Faculty_Summary",     index=False)
        slotdf.to_excel(writer,  sheet_name="Slot_Verification",   index=False)
        alloc.to_excel(writer,   sheet_name="Full_Allocation",     index=False)

    tot = len(alloc); ab2 = alloc["Allocated_By"]
    unmet = slotdf[~slotdf["Status"].str.startswith("✓")]
    gaps  = sumdf[sumdf["Gap"] > 0]
    sub_alloc     = alloc[alloc["Name"].isin(submitted)]
    will_matched  = int(sub_alloc["Allocated_By"].isin(WILL_TAGS).sum()) if not sub_alloc.empty else 0
    will_total_sub = len(sub_alloc)
    overall_match_pct = (will_matched / will_total_sub * 100) if will_total_sub > 0 else 0
    sub_sumdf = sumdf[sumdf["Submitted"] == "Yes"].copy()
    sub_sumdf["_pct"] = sub_sumdf.apply(
        lambda r: r["Willingness_Total"] / r["Assigned_Duties"] * 100 if r["Assigned_Duties"] > 0 else 0, axis=1)
    above80 = int((sub_sumdf["_pct"] >= 80).sum())

    log(f"\n{'=' * 62}\n  RESULTS  [{method}]\n{'=' * 62}")
    log(f"  Total assignments          : {tot}")
    log(f"  ├─ Exact willingness       : {int((ab2 == 'Willingness-Exact').sum())}")
    log(f"  ├─ ACP offline→online      : {int((ab2 == 'Willingness-ACPOnline').sum())}")
    log(f"  ├─ Session flip FN↔AN      : {int((ab2 == 'Willingness-SessionFlip').sum())}")
    log(f"  ├─ Adjacent day ±1         : {int((ab2 == 'Willingness-±1Day').sum())}")
    log(f"  ├─ Adjacent day ±2         : {int((ab2 == 'Willingness-±2Day').sum())}")
    log(f"  └─ Auto-assigned           : {int(ab2.isin(['Auto-Assigned', 'OR-Assigned', 'Gap-Fill']).sum())}")
    log(f"\n  ★ Overall willingness match: {overall_match_pct:.1f}%  ({will_matched}/{will_total_sub})")
    log(f"  ★ Faculty ≥80% match       : {above80}/{len(sub_sumdf)}")
    log(f"\n  Slot fulfilment : {len(slotdf) - len(unmet)}/{len(slotdf)}"
        + (" ✓ ALL MET" if len(unmet) == 0 else f"  ⚠ {len(unmet)} unmet"))
    log(f"  Faculty targets : {len(sumdf) - len(gaps)}/{len(sumdf)}"
        + (" ✓ ALL MET" if len(gaps) == 0 else f"  ⚠ {len(gaps)} short"))
    acp = sumdf[sumdf["Designation"] == "ACP"]
    log(f"  ACP (≥1 online + ≥1 offline): {len(acp[(acp['Online'] >= 1) & (acp['Offline'] >= 1)])}/{len(acp)}")
    log(f"\n  Saved: {FINAL_ALLOC_FILE}  |  {ALLOC_REPORT_FILE}")
    return alloc, sumdf, slotdf, desigdf


# ═══════════════════════════════════════════════════════════════ #
#                   SESSION STATE DEFAULTS                       #
# ═══════════════════════════════════════════════════════════════ #
_defaults = {
    "logged_in":           False,
    "admin_authenticated": False,
    "panel_mode":          "User View",
    "user_panel_mode":     "Willingness",
    "selected_faculty":    "",
    "selected_slots":      [],
    "confirm_delete":      False,
    "pending_submissions": pd.DataFrame(columns=["Faculty", "Date", "Session"]),
}
for k, val in _defaults.items():
    if k not in st.session_state:
        st.session_state[k] = val


# ═══════════════════════════════════════════════════════════════ #
#                         LOGIN                                  #
# ═══════════════════════════════════════════════════════════════ #
if not st.session_state.logged_in:
    render_header(logo=True)
    _, c2, _ = st.columns([1, 2, 1])
    with c2:
        st.markdown(
            '<div class="card"><div class="card-title">🔒 Faculty Login</div>'
            '<p class="card-sub">Enter your credentials to access the portal.</p></div>',
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
    st.caption("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()


# ═══════════════════════════════════════════════════════════════ #
#                      LOAD CORE DATA                            #
# ═══════════════════════════════════════════════════════════════ #
if not os.path.exists(FACULTY_FILE):
    st.error(f"**{FACULTY_FILE}** not found. Upload it to your GitHub repo.")
    st.stop()

fac_df = pd.read_excel(FACULTY_FILE)
fac_df.columns = fac_df.columns.str.strip()
_fc = fac_df.columns.tolist()
fac_df.rename(columns={_fc[0]: "Name", _fc[1]: "Designation"}, inplace=True)
fac_df = fac_df.dropna(subset=["Name"]).reset_index(drop=True)
fac_df["Name"]  = fac_df["Name"].astype(str).str.strip()
fac_df["Clean"] = fac_df["Name"].apply(clean)

offline_df, online_df = load_slots(OFFLINE_FILE, ONLINE_FILE)


# ═══════════════════════════════════════════════════════════════ #
#                  HEADER + NOTICE BANNER                        #
# ═══════════════════════════════════════════════════════════════ #
render_header(logo=False)
st.markdown(
    "<div class='blink'><strong>Note:</strong> The University Examination Committee "
    "sincerely appreciates your cooperation. Every effort will be made to accommodate "
    "your willingness while adhering to institutional requirements. Final duty allocation "
    "is carried out using AI-assisted MILP optimization.</div>",
    unsafe_allow_html=True)
st.markdown("")

panel_mode = st.radio("Main Menu", ["User View", "Admin View"], horizontal=True, key="panel_mode")


# ═══════════════════════════════════════════════════════════════ #
#                        ADMIN VIEW                              #
# ═══════════════════════════════════════════════════════════════ #
if panel_mode == "Admin View":
    st.markdown(
        '<div class="card"><div class="card-title">🔒 Admin View</div>'
        '<p class="card-sub">Protected. Enter admin password to continue.</p></div>',
        unsafe_allow_html=True)
    if not st.session_state.admin_authenticated:
        ap = st.text_input("Admin Password", type="password", key="admpw")
        if st.button("Unlock", use_container_width=True):
            if ap == "sathya":
                st.session_state.admin_authenticated = True
                st.rerun()
            else:
                st.error("Incorrect password.")
    else:
        st.success("✅ Admin unlocked.")

        t1, t2, t3, t4 = st.tabs([
            "📋 Willingness Records",
            "🤖 Run Optimizer",
            "📊 View Results",
            "⚙️ Portal Settings",
        ])

        # ── Tab 1: Willingness Records ────────────────────────────
        with t1:
            st.markdown("### Willingness Records")
            w_all = get_all_willingness()
            if w_all.empty:
                st.info(
                    "No willingness data found.\n\n"
                    "**Workflow:** Faculty submit via User View → "
                    "Download CSV → Save as Willingness.xlsx → Upload to GitHub → Run Optimizer.")
            else:
                vdf = w_all.drop(columns=["FacultyClean"], errors="ignore").reset_index(drop=True)
                if "Sl.No" not in vdf.columns:
                    vdf.insert(0, "Sl.No", vdf.index + 1)
                sub_cnt = vdf["Faculty"].nunique() if "Faculty" in vdf.columns else 0
                c1, c2, c3 = st.columns(3)
                c1.metric("Faculty Submitted", sub_cnt)
                c2.metric("Not Yet Submitted", len(fac_df) - sub_cnt)
                c3.metric("Total Rows",         len(vdf))
                st.dataframe(vdf, use_container_width=True, hide_index=True)
                st.download_button(
                    "⬇ Download Willingness CSV",
                    data=vdf[["Faculty", "Date", "Session"]].to_csv(index=False).encode("utf-8"),
                    file_name="Willingness.csv", mime="text/csv",
                    help="Download → open in Excel → Save As Willingness.xlsx → upload to GitHub")
                st.caption("📌 Download CSV → save as Willingness.xlsx → upload to GitHub → run optimizer.")
            st.markdown("---")
            st.markdown("#### ⚠ Clear In-Session Submissions")
            st.checkbox("Confirm clearing all in-session submissions", key="confirm_delete")
            if st.button("Clear Session Submissions", type="primary"):
                if st.session_state.confirm_delete:
                    st.session_state.pending_submissions = pd.DataFrame(columns=["Faculty", "Date", "Session"])
                    st.success("Cleared.")
                    st.session_state.confirm_delete = False
                    st.rerun()
                else:
                    st.error("Tick the confirmation checkbox first.")

        # ── Tab 2: Run Optimizer ──────────────────────────────────
        with t2:
            st.markdown("### Run Allocation Optimizer")
            def fstat(f): return "✅ Found" if os.path.exists(f) else "❌ Missing"
            wstat = "✅ Found" if os.path.exists(WILLINGNESS_FILE) else "⚠ Not found (all auto-assigned)"
            st.markdown(f"""
| File | Purpose | Status |
|---|---|---|
| `Faculty_Master.xlsx` | Faculty list + designations | {fstat(FACULTY_FILE)} |
| `Offline_Duty.xlsx`   | Offline exam slots          | {fstat(OFFLINE_FILE)} |
| `Online_Duty.xlsx`    | Online exam slots           | {fstat(ONLINE_FILE)} |
| `Willingness.xlsx`    | Faculty willingness         | {wstat} |
""")
            wn = get_all_willingness()
            sc2 = wn["Faculty"].nunique() if not wn.empty and "Faculty" in wn.columns else 0
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Faculty",         len(fac_df))
            c2.metric("Willingness Submitted", f"{sc2}/{len(fac_df)}")
            c3.metric("Willingness Rows",      len(wn))

            if not os.path.exists(FACULTY_FILE) or not os.path.exists(OFFLINE_FILE):
                st.error("Faculty_Master.xlsx and Offline_Duty.xlsx are required.")
            elif not SCIPY_OK:
                st.error("scipy not installed. Add scipy to requirements.txt and redeploy.")
            else:
                st.info(
                    "💡 **Recommended:** Disable the allotment view (Portal Settings) before "
                    "running, then re-enable after reviewing results.")
                if st.button("▶ Run Optimizer", type="primary", use_container_width=True):
                    lb2 = st.empty()
                    with st.spinner("Running MILP optimization..."):
                        try:
                            run_optimizer(lb2)
                            st.success("✅ Optimization complete! Review results, then enable the allotment view in Portal Settings.")
                            st.balloons()
                        except Exception as e:
                            st.error(f"Optimizer error: {e}")

        # ── Tab 3: View Results ───────────────────────────────────
        with t3:
            st.markdown("### Allocation Results")
            if not os.path.exists(FINAL_ALLOC_FILE):
                st.info("No results yet. Run the optimizer first.")
            else:
                av  = pd.read_excel(FINAL_ALLOC_FILE)
                rep = {}
                if os.path.exists(ALLOC_REPORT_FILE):
                    xl2 = pd.ExcelFile(ALLOC_REPORT_FILE)
                    for sh in xl2.sheet_names: rep[sh] = xl2.parse(sh)

                tot2 = len(av)
                if tot2 > 0 and "Allocated_By" in av.columns:
                    ab3    = av["Allocated_By"]
                    will_m = int(ab3.isin(WILL_TAGS).sum())
                    aut    = int(ab3.isin(["Auto-Assigned", "OR-Assigned", "Gap-Fill"]).sum())
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Total Assignments",  int(tot2))
                    c2.metric("Willingness Matched", will_m)
                    c3.metric("Auto-Assigned",        aut)
                    c4.metric("Overall Match %",      f"{will_m / tot2 * 100:.1f}%")

                for sh_name, label in [("Designation_Summary", "Designation Summary"),
                                       ("Slot_Verification",   "Slot Verification"),
                                       ("Faculty_Summary",     "Faculty Summary")]:
                    if sh_name in rep:
                        st.markdown(f"#### {label}")
                        if sh_name == "Slot_Verification" and "Status" in rep[sh_name].columns:
                            um = rep[sh_name][~rep[sh_name]["Status"].str.startswith("✓")]
                            st.metric("Slots Fulfilled",
                                      f"{len(rep[sh_name]) - len(um)}/{len(rep[sh_name])}",
                                      delta="All Met ✓" if len(um) == 0 else f"{len(um)} unmet ⚠")
                        st.dataframe(rep[sh_name], use_container_width=True, hide_index=True)

                # ── Per-faculty deviation drill-down (admin only) ─
                st.markdown("---")
                st.markdown("#### 🔍 Per-Faculty Deviation Analysis")
                st.caption("Select a faculty member to inspect their willingness match and deviation details.")
                admin_fnames = fac_df["Name"].dropna().drop_duplicates().tolist()
                admin_sel    = st.selectbox("Select Faculty", admin_fnames, key="admin_dev_sel")
                admin_sc     = clean(admin_sel)

                wd_admin = load_willingness()
                admin_will_set = set()
                if not wd_admin.empty:
                    wm_admin = fac_mask(wd_admin, admin_sc)
                    wr_admin = wd_admin[wm_admin]
                    if not wr_admin.empty and {"Date", "Session"}.issubset(wr_admin.columns):
                        for d2, s2 in zip(wr_admin["Date"], wr_admin["Session"]):
                            nd = pd.to_datetime(d2, dayfirst=True, errors="coerce")
                            if pd.notna(nd):
                                admin_will_set.add((nd.date(), str(s2).upper()))

                am_admin = fac_mask(av, admin_sc)
                admin_allot_rows = av[am_admin].copy()
                render_deviation_section(admin_allot_rows, admin_will_set)

                st.markdown("---")
                st.markdown("#### Full Allocation Table")
                st.dataframe(av, use_container_width=True, hide_index=True)
                col1, col2 = st.columns(2)
                with col1:
                    with open(FINAL_ALLOC_FILE, "rb") as fh:
                        st.download_button("⬇ Final_Allocation.xlsx", data=fh.read(),
                            file_name="Final_Allocation.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                with col2:
                    with open(ALLOC_REPORT_FILE, "rb") as fh:
                        st.download_button("⬇ Allocation_Report.xlsx", data=fh.read(),
                            file_name="Allocation_Report.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        # ── Tab 4: Portal Settings ────────────────────────────────
        with t4:
            st.markdown("### ⚙️ Portal Settings")
            st.markdown("---")
            st.markdown("#### 🔒 Allotment View — User Access Control")
            st.markdown(
                "Control whether faculty can see their final duty allotment. "
                "**Disable** before running the optimizer so faculty don't see incomplete "
                "results. **Enable** once you have reviewed and approved the allocation.")

            is_open = gate_is_open()

            if is_open:
                st.markdown(
                    "<div style='background:#d1fae5;border:1.5px solid #6ee7b7;"
                    "border-radius:10px;padding:12px 18px;margin-bottom:14px'>"
                    "<span style='font-size:1.05rem;font-weight:700;color:#065f46'>"
                    "🟢  Allotment view is ENABLED — faculty can see their allotment.</span>"
                    "</div>", unsafe_allow_html=True)
            else:
                st.markdown(
                    "<div style='background:#fee2e2;border:1.5px solid #fca5a5;"
                    "border-radius:10px;padding:12px 18px;margin-bottom:14px'>"
                    "<span style='font-size:1.05rem;font-weight:700;color:#991b1b'>"
                    "🔴  Allotment view is DISABLED — faculty see a waiting message.</span>"
                    "</div>", unsafe_allow_html=True)

            en_col, dis_col = st.columns(2)
            with en_col:
                if st.button("✅ Enable Allotment View", use_container_width=True,
                             disabled=is_open, type="primary"):
                    set_gate(True)
                    st.success("Allotment view ENABLED. Faculty can now view their allotment.")
                    st.rerun()
            with dis_col:
                if st.button("🔴 Disable Allotment View", use_container_width=True,
                             disabled=not is_open):
                    set_gate(False)
                    st.warning("Allotment view DISABLED. Faculty will see a waiting message.")
                    st.rerun()

            st.caption(
                "📌 Recommended workflow: Disable → Run Optimizer (Tab 2) → "
                "Review in View Results (Tab 3) → Enable when satisfied.")

            st.markdown("---")
            st.markdown("#### 🔐 Admin Session")
            if st.button("🔒 Lock Admin View", use_container_width=True):
                st.session_state.admin_authenticated = False
                st.rerun()

    st.markdown("---")
    st.caption("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()


# ═══════════════════════════════════════════════════════════════ #
#                        USER VIEW                               #
# ═══════════════════════════════════════════════════════════════ #
user_mode = st.radio("User View", ["Willingness", "Allotment"],
                     horizontal=True, key="user_panel_mode")


# ─── ALLOTMENT VIEW ──────────────────────────────────────────── #
if user_mode == "Allotment":
    st.markdown("### My Allotment Details")

    # Gate check
    if not gate_is_open():
        st.markdown(
            "<div style='background:#fef3c7;border:2px solid #f59e0b;border-radius:12px;"
            "padding:22px 26px;text-align:center;margin:18px 0'>"
            "<div style='font-size:2.2rem;margin-bottom:8px'>⏳</div>"
            "<div style='font-size:1.15rem;font-weight:700;color:#92400e'>"
            "Allotment results are being processed</div>"
            "<div style='font-size:.93rem;color:#78350f;margin-top:6px'>"
            "The Examination Committee is reviewing the final allocation. "
            "Please check back shortly — the allotment will be visible here "
            "once it has been approved and released by the admin.</div>"
            "</div>", unsafe_allow_html=True)
        st.markdown("---")
        st.caption("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
        st.stop()

    fnames = fac_df["Name"].dropna().drop_duplicates().tolist()
    sn = st.selectbox("Select Your Name", fnames, key="aname")
    sc = clean(sn)
    frd = fac_df[fac_df["Clean"] == sc]

    vd, qd = [], []
    if not frd.empty:
        fr2 = frd.iloc[0]
        vd = [f"{fmt_day(d.strftime('%d-%m-%Y'))} - Full Day" for d in valuation_dates_for(fr2)]
        qd = [fmt_day(d) for d in qp_dates_for(fr2)]

    # Load willingness (for WhatsApp message only — not displayed to user)
    wd2 = load_willingness()
    wdisp = []
    if not wd2.empty:
        wm = fac_mask(wd2, sc)
        wr = wd2[wm]
        if not wr.empty and {"Date", "Session"}.issubset(wr.columns):
            for d2, s2 in zip(wr["Date"], wr["Session"]):
                wdisp.append(f"{fmt_day(d2)} - {str(s2).upper()}")

    # Load allotment
    adf = pd.read_excel(FINAL_ALLOC_FILE) if os.path.exists(FINAL_ALLOC_FILE) else pd.DataFrame()
    idisp = []
    if not adf.empty:
        am = fac_mask(adf, sc)
        allot_rows = adf[am].copy()
        if not allot_rows.empty and {"Date", "Session"}.issubset(allot_rows.columns):
            for _, ar in allot_rows.iterrows():
                dtype = str(ar.get("Type", "")).strip()
                idisp.append(f"{fmt_day(ar['Date'])} - {str(ar['Session']).upper()} ({dtype})")

    # ── 4 clean panels for the user ──────────────────────────────
    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="panel"><div class="sec-title">1) Willingness Options Submitted</div></div>',
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": wdisp or ["Not submitted"]}),
                     use_container_width=True, hide_index=True)

        st.markdown('<div class="panel"><div class="sec-title">3) Invigilation Dates (Final Allotment)</div></div>',
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": idisp or ["Not allotted yet"]}),
                     use_container_width=True, hide_index=True)
    with c2:
        st.markdown('<div class="panel"><div class="sec-title">2) Valuation Dates (Full Day)</div></div>',
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": vd or ["Not available"]}),
                     use_container_width=True, hide_index=True)

        st.markdown('<div class="panel"><div class="sec-title">4) QP Feedback Dates</div></div>',
                    unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": qd or ["Not available"]}),
                     use_container_width=True, hide_index=True)

    # ── WhatsApp share (no deviation info for users) ──────────────
    msg = build_msg(sn, wdisp, vd, idisp, qd)
    st.markdown('<div class="panel"><div class="sec-title">📲 Share via WhatsApp</div></div>',
                unsafe_allow_html=True)
    wph = st.text_input("WhatsApp Number (with country code)", placeholder="+919876543210")
    if st.button("Generate WhatsApp Link", use_container_width=True):
        if not wph.strip():
            st.warning("Enter a number.")
        else:
            lnk = wa_link(wph.strip(), msg)
            st.markdown(
                f'<a href="{lnk}" target="_blank" style="display:inline-block;'
                f'background:#25D366;color:white;padding:10px 22px;border-radius:10px;'
                f'font-weight:700;text-decoration:none;">📲 Open WhatsApp & Send</a>',
                unsafe_allow_html=True)
    with st.expander("Preview Message"):
        st.code(msg, language="text")

    st.markdown("---")
    st.caption("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()


# ─── WILLINGNESS SUBMISSION ───────────────────────────────────── #
fnames2   = fac_df["Name"].dropna().drop_duplicates().tolist()
sel_name  = st.selectbox("Select Your Name", fnames2)
sel_clean = clean(sel_name)
fmatch    = fac_df[fac_df["Clean"] == sel_clean]

if fmatch.empty:
    st.error("Faculty not found. Contact admin.")
    st.stop()

frow2   = fmatch.iloc[0]
desig2  = str(frow2["Designation"]).strip().upper()
req_cnt = DUTY_STRUCTURE.get(desig2, 0)
val_d2  = valuation_dates_for(frow2)
val_s2  = set(val_d2)

if req_cnt == 0:
    st.warning(f"Designation '{desig2}' not recognised. Contact admin.")

sopts = online_df.copy() if desig2 == "P" else offline_df.copy()
sopts["Date"]     = pd.to_datetime(sopts["Date"], errors="coerce")
sopts["DateOnly"] = sopts["Date"].dt.date
valid_d = sorted([d for d in sopts["DateOnly"].dropna().unique() if d not in val_s2])

if st.session_state.selected_faculty != sel_clean:
    st.session_state.selected_faculty = sel_clean
    st.session_state.selected_slots   = []
    st.session_state["picked_date"]   = valid_d[0] if valid_d else None

if "picked_date" not in st.session_state:
    st.session_state["picked_date"] = valid_d[0] if valid_d else None

left, right = st.columns([1, 1.4])

with left:
    st.subheader("Willingness Submission")
    st.write(f"**Designation:** {desig2}")
    st.write(f"**Options to Select:** {req_cnt}")

    if desig2 == "ACP":
        st.info(
            "ACP faculty will receive one Online and one Offline duty. "
            "Please select all available dates from the Offline calendar. "
            "Online duty will be assigned automatically from your submitted dates.")

    if not valid_d:
        st.warning("No dates available for selection.")
    else:
        picked = st.selectbox(
            "Choose Online Date" if desig2 == "P" else "Choose Offline Date",
            valid_d, key="picked_date",
            format_func=lambda d: d.strftime("%d-%m-%Y (%A)"))
        avail = set(sopts[sopts["DateOnly"] == picked]["Session"].dropna().astype(str).str.upper())

        # Live probability bars — shown only when applicants >= 3x seats
        all_will_now = get_all_willingness()
        any_prob_shown = False
        for sess_opt in ["FN", "AN"]:
            if sess_opt in avail:
                prob_info = slot_probability(all_will_now, sopts, picked, sess_opt)
                seats_val = prob_info["seats"]
                appl_val  = prob_info["applicants"]
                if seats_val > 0 and appl_val >= 3 * seats_val:
                    render_prob_bar(prob_info, sess_opt)
                    any_prob_shown = True
        if any_prob_shown:
            st.caption("⚡ Probability shown when demand is 3× or more than available seats.")

        b1, b2 = st.columns(2)
        with b1:
            add_fn = st.button("➕ Add FN", use_container_width=True,
                disabled=("FN" not in avail or len(st.session_state.selected_slots) >= req_cnt))
        with b2:
            add_an = st.button("➕ Add AN", use_container_width=True,
                disabled=("AN" not in avail or len(st.session_state.selected_slots) >= req_cnt))

        def add_slot(sess):
            exist = {s["Date"] for s in st.session_state.selected_slots}
            sl2   = {"Date": picked, "Session": sess}
            if picked in val_s2:
                st.warning("Valuation date — cannot select.")
            elif picked in exist:
                st.warning("Both FN and AN on same date not allowed.")
            elif len(st.session_state.selected_slots) >= req_cnt:
                st.warning("Count reached.")
            elif sl2 in st.session_state.selected_slots:
                st.warning("Already selected.")
            else:
                st.session_state.selected_slots.append(sl2)

        if add_fn: add_slot("FN")
        if add_an: add_slot("AN")

    st.session_state.selected_slots = st.session_state.selected_slots[:req_cnt]
    st.write(f"**Selected:** {len(st.session_state.selected_slots)} / {req_cnt}")

    sdf = pd.DataFrame(st.session_state.selected_slots)
    if not sdf.empty:
        sdf = sdf.sort_values(["Date", "Session"]).reset_index(drop=True)
        sdf.insert(0, "Sl.No", sdf.index + 1)
        sdf["Day"]  = pd.to_datetime(sdf["Date"]).dt.day_name()
        sdf["Date"] = pd.to_datetime(sdf["Date"]).dt.strftime("%d-%m-%Y")
        st.dataframe(sdf[["Sl.No", "Date", "Day", "Session"]], use_container_width=True, hide_index=True)
        rm = st.selectbox("Sl.No to remove", options=sdf["Sl.No"].tolist())
        if st.button("🗑 Remove Row", use_container_width=True):
            tgt = sdf[sdf["Sl.No"] == rm].iloc[0]
            td  = pd.to_datetime(tgt["Date"], dayfirst=True).date()
            ts  = tgt["Session"]
            st.session_state.selected_slots = [
                s for s in st.session_state.selected_slots
                if not (s["Date"] == td and s["Session"] == ts)]
            st.rerun()

    wl2 = load_willingness()
    already = (sel_clean in wl2["FacultyClean"].tolist()
               if not wl2.empty and "FacultyClean" in wl2.columns else False)
    pend = st.session_state.get("pending_submissions", pd.DataFrame(columns=["Faculty", "Date", "Session"]))
    if not pend.empty and "Faculty" in pend.columns:
        already = already or (sel_name in pend["Faculty"].tolist())

    st.markdown("### Submit Willingness")
    rem2 = max(req_cnt - len(st.session_state.selected_slots), 0)

    if already:
        st.warning("⚠ You have already submitted your willingness.")
    elif rem2 == 0 and req_cnt > 0:
        st.success(f"✅ All {req_cnt} options selected. Ready to submit.")
    else:
        st.info(f"Select {rem2} more option(s) to enable submission.")

    if st.button("✅ Submit Willingness",
                 disabled=(already or len(st.session_state.selected_slots) != req_cnt),
                 use_container_width=True):
        save_submission(sel_name, st.session_state.selected_slots)
        st.session_state.selected_slots = []
        st.toast("Willingness submitted successfully! ✅", icon="✅")
        st.success(
            "Thank you for submitting. The final duty allocation will be carried out "
            "using MILP optimization. Check this portal for allotment updates.")

with right:
    if desig2 == "P":
        render_calendar(online_df, val_s2, "Online Duty Calendar")
    else:
        render_calendar(offline_df, val_s2, "Offline Duty Calendar")

st.markdown("---")
st.caption("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
