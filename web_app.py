import os
import io
import calendar as calmod
import urllib.parse
import pandas as pd
import streamlit as st
import altair as alt
from collections import defaultdict
from datetime import date, timedelta

# ---------------- CONFIG ---------------- #
FACULTY_FILE          = "Faculty_Master.xlsx"
OFFLINE_FILE          = "Offline_Duty.xlsx"
ONLINE_FILE           = "Online_Duty.xlsx"
WILLINGNESS_FILE      = "Willingness.xlsx"
FINAL_ALLOTMENT_FILE  = "Final_Allocation.xlsx"
LOGO_FILE             = "sastra_logo.png"

# Designation → total duty quota
DUTY_QUOTA = {
    "P":   3,
    "ACP": 5,
    "SAP": 7,
    "AP3": 7,
    "AP2": 7,
    "TA":  9,
    "RA":  9,
}

st.set_page_config(page_title="SASTRA Duty Portal", layout="wide")

st.markdown(
    """
    <style>
    .stApp { background: #f4f7fb; }
    .main .block-container { max-width: 1180px; padding-top: 1.2rem; padding-bottom: 1.2rem; }
    .secure-card {
        background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
        border: 1px solid #dbe3ef; border-radius: 14px; padding: 16px 18px;
        box-shadow: 0 10px 24px rgba(15,23,42,0.08); margin-bottom: 12px;
    }
    .panel-card {
        background: #ffffff; border: 1px solid #e2e8f0; border-radius: 14px;
        padding: 14px 16px; box-shadow: 0 8px 20px rgba(15,23,42,0.06); margin-bottom: 10px;
    }
    .secure-title  { font-size: 1.08rem; font-weight: 700; color: #0f172a; margin-bottom: 0.2rem; }
    .secure-sub    { font-size: 0.93rem; color: #334155; margin-bottom: 0; }
    .section-title { font-size: 1rem; font-weight: 700; color: #0b3a67; margin-bottom: 0.35rem; }
    .stButton>button         { border-radius: 10px; border: 1px solid #cbd5e1; font-weight: 600; }
    .stDownloadButton>button { border-radius: 10px; font-weight: 600; }
    [data-testid="stRadio"] label p { font-weight: 600; }
    .blink-notice {
        font-weight: 700; color: #800000; padding: 10px 12px;
        border: 2px solid #800000; background: #fffaf5; border-radius: 6px;
        animation: blinkPulse 2.4s ease-in-out infinite;
    }
    @keyframes blinkPulse { 0%{opacity:1} 50%{opacity:0.35} 100%{opacity:1} }
    </style>
    """,
    unsafe_allow_html=True,
)


# ═══════════════════════ UTILITY FUNCTIONS ═══════════════════════

def clean(x):
    return str(x).strip().lower()

def normalize_session(value):
    t = str(value).strip().upper()
    if t in {"FN","FORENOON","MORNING","AM"}: return "FN"
    if t in {"AN","AFTERNOON","EVENING","PM"}:  return "AN"
    return t

def load_excel(file_path):
    if not os.path.exists(file_path):
        st.error(f"{file_path} not found in repository.")
        st.stop()
    return pd.read_excel(file_path)

def normalize_duty_df(df):
    df = df.copy(); df.columns = df.columns.str.strip()
    if len(df.columns) < 3:
        st.error("Duty files must include Date, Session, and Required columns."); st.stop()
    df.rename(columns={df.columns[0]:"Date", df.columns[1]:"Session", df.columns[2]:"Required"}, inplace=True)
    df["Date"]     = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df             = df.dropna(subset=["Date"]).copy()
    df["Session"]  = df["Session"].apply(normalize_session)
    df["Required"] = pd.to_numeric(df["Required"], errors="coerce").fillna(1).astype(int)
    return df

def valuation_dates_for_faculty(faculty_row):
    dates = []
    for col in ["V1","V2","V3","V4","V5"]:
        if col in faculty_row.index and pd.notna(faculty_row[col]):
            dates.append(pd.to_datetime(faculty_row[col], dayfirst=True).date())
    return sorted(set(dates))

def demand_category(required):
    if required < 3:    return "Low (<3)"
    if required <= 7:   return "Medium (3-7)"
    return "High (>7)"

def load_willingness():
    if os.path.exists(WILLINGNESS_FILE):
        df = pd.read_excel(WILLINGNESS_FILE)
        if "Faculty" not in df.columns: df["Faculty"] = ""
        df["FacultyClean"] = df["Faculty"].apply(clean)
        return df
    return pd.DataFrame(columns=["Faculty","Date","Session","FacultyClean"])

def load_final_allotment():
    if os.path.exists(FINAL_ALLOTMENT_FILE):
        try: return pd.read_excel(FINAL_ALLOTMENT_FILE)
        except: return pd.DataFrame()
    return pd.DataFrame()

def faculty_match_mask(df, selected_clean):
    if df.empty: return pd.Series([], dtype=bool)
    name_cols = [c for c in df.columns if "name" in str(c).lower() or "faculty" in str(c).lower()]
    if not name_cols: return pd.Series([False]*len(df), index=df.index)
    mask = pd.Series([False]*len(df), index=df.index)
    for col in name_cols:
        mask = mask | (df[col].astype(str).apply(clean) == selected_clean)
    return mask

def collect_qp_feedback_dates(faculty_row):
    qp_dates = []
    for col in faculty_row.index:
        col_text = str(col).strip().upper()
        if "QP" in col_text and "DATE" in col_text:
            val = faculty_row[col]
            if pd.notna(val):
                dt = pd.to_datetime(val, dayfirst=True, errors="coerce")
                if pd.notna(dt): qp_dates.append(dt.strftime("%d-%m-%Y"))
    return sorted(set(qp_dates))

def format_with_day(date_text):
    dt = pd.to_datetime(date_text, dayfirst=True, errors="coerce")
    if pd.isna(dt): return str(date_text).strip()
    return f"{dt.strftime('%d-%m-%Y')} ({dt.strftime('%A')})"

def build_delivery_message(name, willingness_list, valuation_list, invigilation_list, qp_list, accommodated_pct):
    lines = [
        f"Dear {name},", "",
        "Here are your Examination Duty Details:", "",
        "1) Invigilation Dates (Final Allotment):",
        *(invigilation_list or ["Not allotted yet"]), "",
        "2) Valuation Dates (Full Day):",
        *(valuation_list or ["Not available"]), "",
        "3) QP Feedback Dates:",
        *(qp_list or ["Not available"]), "",
        "- SASTRA SoME Examination Committee",
    ]
    return "\n".join(lines)

def get_whatsapp_link(phone, message):
    clean_phone = str(phone).strip().replace("+","").replace(" ","").replace("-","")
    return f"https://wa.me/{clean_phone}?text={urllib.parse.quote(message)}"

def render_branding_header(show_logo=True):
    if show_logo and os.path.exists(LOGO_FILE):
        c1,c2,c3 = st.columns([2,1,2])
        with c2: st.image(LOGO_FILE, width=180)
    st.markdown("<h2 style='text-align:center;margin-bottom:0.25rem;'>SASTRA SoME End Semester Examination Duty Portal</h2>", unsafe_allow_html=True)
    st.markdown("<h4 style='text-align:center;margin-top:0;'>School of Mechanical Engineering</h4>", unsafe_allow_html=True)
    st.markdown("---")

def build_month_calendar_frame(duty_df, valuation_dates_set, year, month):
    session_demand = duty_df.groupby(["Date","Session"], as_index=False)["Required"].sum()
    demand_map = {
        (d.date(), str(sess).upper()): int(req)
        for d,sess,req in zip(session_demand["Date"], session_demand["Session"], session_demand["Required"])
    }
    month_start   = pd.Timestamp(year=year, month=month, day=1)
    month_end     = month_start + pd.offsets.MonthEnd(0)
    month_days    = pd.date_range(month_start, month_end, freq="D")
    first_weekday = month_start.weekday()
    weekday_labels = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    rows = []
    for dt in month_days:
        week_no   = ((dt.day + first_weekday - 1) // 7) + 1
        date_only = dt.date()
        for session in ["FN","AN"]:
            req      = demand_map.get((date_only, session), 0)
            category = ("Valuation Locked" if date_only in valuation_dates_set
                        else ("No Duty" if req == 0 else demand_category(req)))
            rows.append({"Date":dt,"Week":week_no,"Weekday":weekday_labels[dt.weekday()],
                         "DayNum":dt.day,"Session":session,"Required":req,
                         "Category":category,"DateLabel":dt.strftime("%d-%m-%Y")})
    return pd.DataFrame(rows)

def render_month_calendars(duty_df, valuation_dates_set, title):
    st.markdown(f"#### {title}")
    months = sorted({(d.year, d.month) for d in duty_df["Date"]})
    color_scale = alt.Scale(
        domain=["No Duty","Low (<3)","Medium (3-7)","High (>7)","Valuation Locked"],
        range=["#ececec","#2ca02c","#f1c40f","#d62728","#ff69b4"],
    )
    st.markdown("**Heat Map Legend:** ⬜ No Duty  🟩 Low (<3)  🟨 Medium (3-7)  🟥 High (>7)  🩷 Valuation Locked")
    for year, month in months:
        frame      = build_month_calendar_frame(duty_df, valuation_dates_set, year, month)
        high_count = int((frame["Category"] == "High (>7)").sum())
        st.markdown(f"**{calmod.month_name[month]} {year}**")
        st.caption(f"High-demand session slots (>7): {high_count}")
        base = alt.Chart(frame).encode(
            x=alt.X("Weekday:N", sort=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"], title=""),
            xOffset=alt.XOffset("Session:N", sort=["FN","AN"], title=""),
            y=alt.Y("Week:O", sort="ascending", title=""),
            tooltip=[alt.Tooltip("DateLabel:N",title="Date"), alt.Tooltip("Session:N",title="Session"),
                     alt.Tooltip("Required:Q",title="Demand"), alt.Tooltip("Category:N",title="Category")],
        )
        rect     = base.mark_rect(stroke="white").encode(
            color=alt.Color("Category:N", scale=color_scale, legend=alt.Legend(title="Heat Map Legend")))
        day_text = (alt.Chart(frame[frame["Session"]=="FN"])
                    .mark_text(color="black", fontSize=11, dy=-6)
                    .encode(x=alt.X("Weekday:N",sort=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]),
                            y=alt.Y("Week:O",sort="ascending"), text=alt.Text("DayNum:Q")))
        st.altair_chart((rect + day_text).properties(height=230), use_container_width=True)
        st.caption("Each date is split into two halves: left = FN, right = AN.")


# ═══════════════════════ OR-TOOLS ALLOCATION ENGINE ═══════════════════════

def _working_days_set(all_dates):
    """Return set of dates that are weekdays (Mon–Sat, no strict holiday check)."""
    return {d for d in all_dates if d.weekday() < 6}   # 0=Mon … 5=Sat, 6=Sun

def _nearest_available_slots(val_date, available_slot_set, max_delta=14):
    """
    Given one valuation date, return nearby (date,session) pairs from
    available_slot_set sorted by proximity (days difference).
    Searches both before and after val_date within max_delta working days.
    """
    candidates = []
    for d, sess in available_slot_set:
        delta = abs((d - val_date).days)
        if 0 < delta <= max_delta:          # delta=0 excluded (same day = valuation)
            candidates.append((delta, d, sess))
    candidates.sort()
    return [(d, sess) for _, d, sess in candidates]


def run_or_tools_allocation(faculty_df, will_df, offline_df, online_df, time_limit=120):
    """
    Full CP-SAT allocation.

    Priority:
      1. Assign IG duty on dates faculty expressed willingness.
      2. If quota cannot be met by willingness alone, assign the
         remaining duties to slots closest (in calendar distance) to
         that faculty's valuation dates (either side, working day).

    Returns (result_df, unfilled_df, status_name, log_lines)
    """
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return None, None, "ortools_not_installed", ["pip install ortools"]

    log = []

    # ── build slot demand ──────────────────────────────────────────
    slot_demand = {}
    for _, r in offline_df.iterrows():
        k = (r["Date"].date(), r["Session"], "Offline")
        slot_demand[k] = slot_demand.get(k, 0) + int(r["Required"])
    for _, r in online_df.iterrows():
        k = (r["Date"].date(), r["Session"], "Online")
        slot_demand[k] = slot_demand.get(k, 0) + int(r["Required"])
    all_slots = sorted(slot_demand.keys())          # (date, session, mode)
    log.append(f"Total demand slots: {len(all_slots)}")

    # ── all available (date,session) pairs per mode ────────────────
    offline_date_sess = {(r["Date"].date(), r["Session"]) for _, r in offline_df.iterrows()}
    online_date_sess  = {(r["Date"].date(), r["Session"]) for _, r in online_df.iterrows()}

    # ── build faculty records ──────────────────────────────────────
    faculties = []
    for _, row in faculty_df.iterrows():
        des   = str(row.get("DesKey","")).strip().upper()
        quota = DUTY_QUOTA.get(des, 0)
        if quota == 0:
            log.append(f"SKIP (unknown designation '{des}'): {row['Name']}")
            continue

        val_dates   = set(valuation_dates_for_faculty(row))
        fc          = row["Clean"]
        will_rows   = will_df[will_df["FacultyClean"] == fc]
        willing_set = {(pd.to_datetime(wr["Date"], dayfirst=True).date(),
                        normalize_session(wr["Session"]))
                       for _, wr in will_rows.iterrows()}

        if des == "P":
            allowed_modes = {"Online"}
            base_pool     = online_date_sess
        elif des == "ACP":
            allowed_modes = {"Offline","Online"}
            base_pool     = offline_date_sess | online_date_sess
        else:
            allowed_modes = {"Offline"}
            base_pool     = offline_date_sess

        # eligible slots (no valuation conflict)
        eligible_ds = {(d,s) for d,s in base_pool if d not in val_dates}

        # per-slot priority score (higher = prefer more)
        # willingness → score 1000  (highest)
        # near valuation (closer = higher) → score 1..499
        priority = {}
        for d, s in eligible_ds:
            if (d, s) in willing_set:
                priority[(d, s)] = 1000
            else:
                # compute min calendar distance to any valuation date
                if val_dates:
                    min_delta = min(abs((d - v).days) for v in val_dates)
                    # nearer = higher score; cap contribution at 499
                    proximity_score = max(0, 499 - min_delta)
                else:
                    proximity_score = 0
                priority[(d, s)] = proximity_score

        faculties.append({
            "name":          row["Name"],
            "clean":         fc,
            "des":           des,
            "quota":         quota,
            "val_dates":     val_dates,
            "willing_set":   willing_set,
            "allowed_modes": allowed_modes,
            "eligible_ds":   eligible_ds,
            "priority":      priority,
        })

    log.append(f"Faculty processed: {len(faculties)}")

    # ── build CP-SAT model ─────────────────────────────────────────
    model  = cp_model.CpModel()
    x      = {}   # (fi, si) → BoolVar

    for fi, fac in enumerate(faculties):
        for si, slot in enumerate(all_slots):
            d, sess, mode = slot
            if mode not in fac["allowed_modes"]: continue
            if (d, sess) not in fac["eligible_ds"]:  continue
            x[(fi, si)] = model.new_bool_var(f"x_{fi}_{si}")

    # ── constraint: slot demand (with soft slack) ──────────────────
    slot_slack = {}
    for si, slot in enumerate(all_slots):
        demand   = slot_demand[slot]
        assigned = [x[(fi, si)] for fi in range(len(faculties)) if (fi, si) in x]
        if not assigned:
            log.append(f"WARN: No eligible faculty for slot {slot}")
            continue
        slack = model.new_int_var(0, demand, f"slack_{si}")
        slot_slack[si] = slack
        model.add(sum(assigned) + slack == demand)

    # ── constraint: faculty quota (with soft under/over) ──────────
    faculty_slack = {}
    for fi, fac in enumerate(faculties):
        assigned = [x[(fi, si)] for si in range(len(all_slots)) if (fi, si) in x]
        if not assigned: continue
        under = model.new_int_var(0, fac["quota"], f"under_{fi}")
        over  = model.new_int_var(0, fac["quota"], f"over_{fi}")
        faculty_slack[fi] = (under, over)
        model.add(sum(assigned) - over + under == fac["quota"])

    # ── constraint: no FN+AN same date per faculty ────────────────
    fac_date_vars = defaultdict(list)
    for (fi, si), var in x.items():
        d, sess, mode = all_slots[si]
        fac_date_vars[(fi, d)].append(var)
    for vl in fac_date_vars.values():
        if len(vl) > 1:
            model.add(sum(vl) <= 1)

    # ── constraint: ACP → exactly 1 online ────────────────────────
    for fi, fac in enumerate(faculties):
        if fac["des"] == "ACP":
            ov = [x[(fi,si)] for si,slot in enumerate(all_slots)
                  if slot[2]=="Online" and (fi,si) in x]
            if ov: model.add(sum(ov) == 1)

    # ── objective ──────────────────────────────────────────────────
    # Weighted sum: priority score per assignment − heavy penalty for unmet demand
    # − lighter penalty for quota deviation
    obj_terms = []
    for (fi, si), var in x.items():
        d, sess, mode = all_slots[si]
        fac           = faculties[fi]
        score         = fac["priority"].get((d, sess), 0)
        obj_terms.append(score * var)

    slot_penalty    = sum(slot_slack.values())   if slot_slack    else 0
    faculty_penalty = sum(u + o for u, o in faculty_slack.values()) if faculty_slack else 0

    model.maximize(
        sum(obj_terms)
        - 5000 * slot_penalty
        - 500  * faculty_penalty
    )

    # ── solve ──────────────────────────────────────────────────────
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit
    solver.parameters.num_search_workers  = 4
    status      = solver.solve(model)
    status_name = solver.status_name(status)
    log.append(f"Solver status: {status_name}")

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, None, status_name, log

    # ── extract results ────────────────────────────────────────────
    records = []
    for (fi, si), var in x.items():
        if solver.value(var) == 1:
            d, sess, mode = all_slots[si]
            fac           = faculties[fi]
            in_will       = (d, sess) in fac["willing_set"]

            # determine reason label
            if in_will:
                reason = "Willingness Match"
            else:
                if fac["val_dates"]:
                    min_delta = min(abs((d - v).days) for v in fac["val_dates"])
                    reason = f"Near Valuation ({min_delta}d away)"
                else:
                    reason = "Force-Assigned"

            records.append({
                "Faculty":      fac["name"],
                "Designation":  fac["des"],
                "Date":         d.strftime("%d-%m-%Y"),
                "Session":      sess,
                "Mode":         mode,
                "Allot_Reason": reason,
            })

    result_df = (pd.DataFrame(records)
                 .sort_values(["Date","Session","Mode","Faculty"])
                 .reset_index(drop=True))

    # ── unfilled slots ─────────────────────────────────────────────
    unfilled = []
    for si, slot in enumerate(all_slots):
        demand = slot_demand[slot]
        cnt    = sum(solver.value(x[(fi,si)]) for fi in range(len(faculties)) if (fi,si) in x)
        if cnt < demand:
            unfilled.append({"Date":slot[0].strftime("%d-%m-%Y"),"Session":slot[1],
                             "Mode":slot[2],"Required":demand,"Assigned":cnt,"Shortfall":demand-cnt})
    unf_df = pd.DataFrame(unfilled) if unfilled else pd.DataFrame()

    # ── per-faculty quota log ──────────────────────────────────────
    counts = result_df.groupby(["Faculty","Designation"]).size().reset_index(name="Assigned")
    for _, row in counts.iterrows():
        q = DUTY_QUOTA.get(row["Designation"],"?")
        mark = "✅" if row["Assigned"]==q else "⚠"
        log.append(f"  {mark} {row['Faculty']:35s} [{row['Designation']}]  {row['Assigned']}/{q}")

    return result_df, unf_df, status_name, log


# ═══════════════════════ ALLOCATION ADMIN PANEL ═══════════════════════

def render_allocation_admin(faculty_df, will_df, offline_df, online_df):
    st.markdown("---")
    st.markdown("## 🤖 AI Duty Allocation — Google OR-Tools CP-SAT")

    st.info(
        "**How allocation works:**\n\n"
        "1. **Willingness-first** — every willing (date, session) option is strongly preferred.\n"
        "2. **Near-valuation fallback** — if quota cannot be met from willingness alone, "
        "the solver assigns the closest available working slot **before or after** each "
        "faculty's valuation dates (whichever is nearer on the calendar).\n"
        "3. **Hard constraints** — valuation dates are blocked, no FN+AN same day, "
        "mode rules (P→online, ACP→1 online+rest offline, others→offline), exact quota per designation.\n"
        "4. **Slot demand** — every exam slot is filled to its required headcount."
    )

    col1, col2 = st.columns(2)
    with col1:
        time_limit = st.slider("Solver time limit (seconds)", 30, 300, 120, step=30)
    with col2:
        st.markdown("**Files used:**")
        for f in [FACULTY_FILE, WILLINGNESS_FILE, OFFLINE_FILE, ONLINE_FILE]:
            icon = "✅" if os.path.exists(f) else "❌"
            st.caption(f"{icon} `{f}`")

    if st.button("▶ Run OR-Tools Allocation", type="primary", use_container_width=True):
        prog = st.progress(0, text="Preparing …")

        # prepare faculty_df for solver (add DesKey, Clean if missing)
        fdf = faculty_df.copy()
        if "DesKey" not in fdf.columns:
            fdf["DesKey"] = fdf["Designation"].astype(str).str.strip().str.upper()
        if "Clean" not in fdf.columns:
            fdf["Clean"] = fdf["Name"].apply(clean)

        # prepare willingness
        wdf = will_df.copy()
        if "FacultyClean" not in wdf.columns:
            wdf["FacultyClean"] = wdf["Faculty"].apply(clean)

        prog.progress(10, text="Running solver …")
        result_df, unf_df, status_name, log_lines = run_or_tools_allocation(
            fdf, wdf, offline_df, online_df, time_limit=time_limit
        )
        prog.progress(100, text="Done!")
        prog.empty()

        st.markdown(f"**Solver status:** `{status_name}`")

        if result_df is None:
            if status_name == "ortools_not_installed":
                st.error("**ortools not installed.** Run: `pip install ortools` and restart the app.")
            else:
                st.error("No feasible solution found. Check demand vs available faculty.")
            with st.expander("Solver log"):
                st.code("\n".join(log_lines))
            return

        # ── save ──────────────────────────────────────────────────
        result_df.to_excel(FINAL_ALLOTMENT_FILE, index=False)
        if unf_df is not None and not unf_df.empty:
            unf_df.to_excel("Unfilled_Slots.xlsx", index=False)

        # ── metrics ───────────────────────────────────────────────
        total    = len(result_df)
        wm       = (result_df["Allot_Reason"] == "Willingness Match").sum()
        nv       = result_df["Allot_Reason"].str.startswith("Near Valuation").sum()
        force    = total - wm - nv

        st.success(f"✅ Allocation complete — **{total}** assignments written to `{FINAL_ALLOTMENT_FILE}`")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Assignments", total)
        m2.metric("✅ Willingness Match", f"{wm}  ({wm/total*100:.0f}%)")
        m3.metric("📅 Near Valuation",    f"{nv}  ({nv/total*100:.0f}%)")
        m4.metric("⚡ Force-Assigned",    f"{force}")

        # ── unfilled ──────────────────────────────────────────────
        st.markdown("### ⚠ Unfilled Demand Slots")
        if unf_df is not None and not unf_df.empty:
            st.dataframe(unf_df, use_container_width=True, hide_index=True)
            buf = io.BytesIO(); unf_df.to_excel(buf, index=False); buf.seek(0)
            st.download_button("Download Unfilled_Slots.xlsx", buf, "Unfilled_Slots.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        else:
            st.success("All demand slots fully filled! ✅")

        # ── per-faculty summary ───────────────────────────────────
        st.markdown("### 📋 Per-Faculty Summary")
        counts = result_df.groupby(["Faculty","Designation"]).size().reset_index(name="Assigned")
        counts["Quota"]  = counts["Designation"].map(DUTY_QUOTA)
        counts["Status"] = counts.apply(
            lambda r: "✅ Met" if r["Assigned"]==r["Quota"]
                      else (f"⚠ Short {r['Quota']-r['Assigned']}" if r["Assigned"]<r["Quota"]
                            else f"⚠ Over  {r['Assigned']-r['Quota']}"), axis=1)
        counts["Will.Match"] = counts["Faculty"].map(
            result_df[result_df["Allot_Reason"]=="Willingness Match"]
            .groupby("Faculty").size())
        counts["Will.Match"] = counts["Will.Match"].fillna(0).astype(int)
        counts.insert(0,"Sl.No", range(1, len(counts)+1))
        st.dataframe(counts, use_container_width=True, hide_index=True)

        # ── full table with reason ────────────────────────────────
        st.markdown("### 📄 Full Allocation Table")
        view = result_df.copy().reset_index(drop=True)
        view.insert(0, "Sl.No", view.index+1)
        # colour-code reason column
        def colour_reason(val):
            if val == "Willingness Match": return "background-color:#d4edda"
            if str(val).startswith("Near Valuation"): return "background-color:#fff3cd"
            return "background-color:#f8d7da"
        st.dataframe(view.style.applymap(colour_reason, subset=["Allot_Reason"]),
                     use_container_width=True, hide_index=True)

        # ── downloads ─────────────────────────────────────────────
        st.markdown("### ⬇ Downloads")
        c1, c2 = st.columns(2)
        with c1:
            buf = io.BytesIO(); result_df.to_excel(buf, index=False); buf.seek(0)
            st.download_button("📥 Final_Allocation.xlsx", buf, "Final_Allocation.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               use_container_width=True)
        with c2:
            csv = result_df.to_csv(index=False).encode("utf-8")
            st.download_button("📥 Final_Allocation.csv", csv, "Final_Allocation.csv",
                               mime="text/csv", use_container_width=True)

        with st.expander("📋 Solver log"):
            st.code("\n".join(log_lines))


# ═══════════════════════ LOGIN ═══════════════════════

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    render_branding_header(show_logo=True)
    c1,c2,c3 = st.columns([1,2,1])
    with c2:
        st.markdown("""
            <div class="secure-card">
                <div class="secure-title">🔒 Faculty Login</div>
                <p class="secure-sub">Enter your authorized credentials to access the duty portal.</p>
            </div>""", unsafe_allow_html=True)
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Sign In", use_container_width=True):
            if username == "SASTRA" and password == "SASTRA":
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("Invalid credentials")
    st.markdown("---")
    st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()

# ─── session state defaults ──────────────────────────────────────
for k, v in [("admin_authenticated", False), ("panel_mode", "User View"),
             ("confirm_delete_willingness", False), ("selected_slots", []),
             ("selected_faculty", ""), ("acp_notice_shown_for", ""),
             ("user_panel_mode", "Willingness")]:
    if k not in st.session_state:
        st.session_state[k] = v

# ═══════════════════════ LOAD DATA ═══════════════════════

faculty_df  = load_excel(FACULTY_FILE)
offline_df  = normalize_duty_df(load_excel(OFFLINE_FILE))
online_df   = normalize_duty_df(load_excel(ONLINE_FILE))

faculty_df.columns = faculty_df.columns.str.strip()
if len(faculty_df.columns) < 2:
    st.error("Faculty_Master.xlsx must have Name and Designation columns."); st.stop()
faculty_df.rename(columns={faculty_df.columns[0]:"Name", faculty_df.columns[1]:"Designation"}, inplace=True)
faculty_df["Clean"]  = faculty_df["Name"].apply(clean)
faculty_df["DesKey"] = faculty_df["Designation"].astype(str).str.strip().str.upper()

# ═══════════════════════ HEADER ═══════════════════════

render_branding_header(show_logo=False)
st.markdown(
    "<div class='blink-notice'><strong>Note:</strong> The University Examination Committee "
    "sincerely appreciates your cooperation. Every effort will be made to accommodate your "
    "willingness, while ensuring adherence to institutional requirements and examination needs. "
    "The final duty allocation will be carried out using AI-assisted optimization integrated "
    "with Google OR-Tools.</div>", unsafe_allow_html=True)

# ═══════════════════════ MAIN MENU ═══════════════════════

st.markdown('<div class="panel-card"><div class="section-title">Control Panel</div>'
            '<p class="secure-sub">Choose Admin View or User View.</p></div>', unsafe_allow_html=True)
panel_mode = st.radio("Main Menu", ["Admin View","User View"], horizontal=True, key="panel_mode")

# ═══════════════════════ ADMIN VIEW ═══════════════════════

if panel_mode == "Admin View":
    st.markdown("""
        <div class="secure-card">
            <div class="secure-title">🔒 Admin View (Secure Access)</div>
            <p class="secure-sub">Administrative functions are protected. Please authenticate to continue.</p>
        </div>""", unsafe_allow_html=True)

    if not st.session_state.admin_authenticated:
        admin_pass = st.text_input("Admin Password", type="password", key="admin_password")
        if st.button("Unlock Admin View", key="unlock_admin", use_container_width=True):
            if admin_pass == "sathya":
                st.session_state.admin_authenticated = True
                st.success("Admin access granted."); st.rerun()
            else:
                st.error("Invalid admin password.")
    else:
        st.success("✅ Admin view unlocked")

        # ── Willingness records table ─────────────────────────────
        st.markdown("### 📊 Submitted Willingness Records")
        willingness_admin = load_willingness().drop(columns=["FacultyClean"], errors="ignore")
        if willingness_admin.empty:
            st.info("No willingness submissions yet.")
        else:
            view_df = willingness_admin.copy().reset_index(drop=True)
            view_df.insert(0,"Sl.No", view_df.index+1)
            st.dataframe(view_df, use_container_width=True, hide_index=True)
            csv_data = view_df.to_csv(index=False).encode("utf-8")
            st.download_button("Download Willingness CSV", data=csv_data,
                               file_name="Willingness_Admin_View.csv", mime="text/csv",
                               key="download_willingness_csv")

        # ── Allocation panel ──────────────────────────────────────
        will_df_for_alloc = load_willingness()
        render_allocation_admin(faculty_df, will_df_for_alloc, offline_df, online_df)

        # ── Delete willingness ────────────────────────────────────
        st.markdown("---")
        st.markdown("#### 🗑 Delete All Willingness Records")
        st.checkbox("I confirm deletion of all submitted willingness records",
                    key="confirm_delete_willingness")
        if st.button("Delete All Willingness", key="delete_all_willingness", type="primary"):
            if st.session_state.confirm_delete_willingness:
                pd.DataFrame(columns=["Faculty","Date","Session"]).to_excel(WILLINGNESS_FILE, index=False)
                st.success("All willingness records deleted.")
                st.session_state.confirm_delete_willingness = False; st.rerun()
            else:
                st.error("Please confirm deletion before proceeding.")

        if st.button("Lock Admin View", key="lock_admin", use_container_width=True):
            st.session_state.admin_authenticated = False
            st.success("Admin view locked."); st.rerun()

    st.markdown("---")
    st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()

# ═══════════════════════ USER VIEW ═══════════════════════

st.markdown('<div class="panel-card"><div class="section-title">User View Menu</div>'
            '<p class="secure-sub">Choose the required user function.</p></div>', unsafe_allow_html=True)
user_panel_mode = st.radio("User View Menu", ["Willingness","Allotment"],
                           horizontal=True, key="user_panel_mode")

# ─────────────────────── ALLOTMENT TAB ───────────────────────────

if user_panel_mode == "Allotment":
    st.markdown("### Allotment Details")
    faculty_names         = faculty_df["Name"].dropna().drop_duplicates().tolist()
    selected_name_allot   = st.selectbox("Select Faculty", faculty_names, key="allotment_faculty")
    selected_clean_allot  = clean(selected_name_allot)

    faculty_row_df_allot  = faculty_df[faculty_df["Clean"] == selected_clean_allot]
    valuation_display, qp_feedback_display = [], []
    if not faculty_row_df_allot.empty:
        faculty_row_allot  = faculty_row_df_allot.iloc[0]
        valuation_display  = [f"{format_with_day(d.strftime('%d-%m-%Y'))} - Full Day"
                              for d in valuation_dates_for_faculty(faculty_row_allot)]
        qp_feedback_display = [format_with_day(d) for d in collect_qp_feedback_dates(faculty_row_allot)]

    willingness_df_allot  = load_willingness()
    willingness_display, willingness_pairs = [], set()
    if not willingness_df_allot.empty:
        mask = faculty_match_mask(willingness_df_allot, selected_clean_allot)
        rows = willingness_df_allot[mask].copy()
        if not rows.empty and {"Date","Session"}.issubset(rows.columns):
            for d,sess in zip(rows["Date"], rows["Session"]):
                date_fmt = format_with_day(d)
                sess_fmt = str(sess).strip().upper()
                willingness_display.append(f"{date_fmt} - {sess_fmt}")
                nd = pd.to_datetime(d, dayfirst=True, errors="coerce")
                if pd.notna(nd): willingness_pairs.add((nd.date(), sess_fmt))

    allotment_df = load_final_allotment()
    invigilation_display, invigilation_pairs = [], set()
    if not allotment_df.empty:
        amask = faculty_match_mask(allotment_df, selected_clean_allot)
        arows = allotment_df[amask].copy()
        if not arows.empty:
            if {"Date","Session"}.issubset(arows.columns):
                for d,sess in zip(arows["Date"], arows["Session"]):
                    date_fmt = format_with_day(d)
                    sess_fmt = str(sess).strip().upper()
                    invigilation_display.append(f"{date_fmt} - {sess_fmt}")
                    nd = pd.to_datetime(d, dayfirst=True, errors="coerce")
                    if pd.notna(nd): invigilation_pairs.add((nd.date(), sess_fmt))
            else:
                invigilation_display = ["Final allotment available (date/session columns not found)."]

    accommodated_pct = "Not available"
    if willingness_pairs:
        matched = len(willingness_pairs.intersection(invigilation_pairs))
        accommodated_pct = f"{matched/len(willingness_pairs)*100:.2f}% ({matched}/{len(willingness_pairs)})"

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="panel-card"><div class="section-title">1) Willingness Options Given</div></div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": willingness_display or ["Not available"]}), use_container_width=True, hide_index=True)
        st.markdown('<div class="panel-card"><div class="section-title">3) Invigilation Dates (Final Allotment)</div></div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": invigilation_display or ["Not available"]}), use_container_width=True, hide_index=True)
    with c2:
        st.markdown('<div class="panel-card"><div class="section-title">2) Valuation Dates (Full Day)</div></div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": valuation_display or ["Not available"]}), use_container_width=True, hide_index=True)
        st.markdown('<div class="panel-card"><div class="section-title">4) QP Feedback Dates</div></div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": qp_feedback_display or ["Not available"]}), use_container_width=True, hide_index=True)

    st.markdown('<div class="panel-card"><div class="section-title">Willingness Accommodation</div></div>', unsafe_allow_html=True)
    st.info(f"% of willingness accommodated with final allotment: {accommodated_pct}")

    message_text = build_delivery_message(selected_name_allot, willingness_display,
                                          valuation_display, invigilation_display,
                                          qp_feedback_display, accommodated_pct)

    st.markdown('<div class="panel-card"><div class="section-title">📲 Share via WhatsApp</div>'
                '<p class="secure-sub">Enter the recipient\'s WhatsApp number to share the allotment summary.</p></div>',
                unsafe_allow_html=True)
    wa_phone = st.text_input("WhatsApp Number (with country code)", placeholder="e.g., +919876543210", key="whatsapp_phone")
    if st.button("Generate WhatsApp Link", key="generate_wa_link", use_container_width=True):
        if not wa_phone.strip():
            st.warning("Please enter a WhatsApp number.")
        else:
            wa_link = get_whatsapp_link(wa_phone.strip(), message_text)
            st.success("WhatsApp link generated! Click the button below to open WhatsApp.")
            st.markdown(
                f'<a href="{wa_link}" target="_blank" style="display:inline-block;'
                f'background-color:#25D366;color:white;padding:10px 22px;border-radius:10px;'
                f'font-weight:700;text-decoration:none;font-size:1rem;">📲 Open WhatsApp & Send</a>',
                unsafe_allow_html=True)
            st.caption("Opens WhatsApp (web or app) with the message pre-filled.")

    with st.expander("Preview Message"):
        st.code(message_text, language="text")

    st.markdown("---")
    st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()

# ─────────────────────── WILLINGNESS TAB ─────────────────────────

faculty_names  = faculty_df["Name"].dropna().drop_duplicates().tolist()
selected_name  = st.selectbox("Select Your Name", faculty_names)
selected_clean = clean(selected_name)
faculty_row_df = faculty_df[faculty_df["Clean"] == selected_clean]
if faculty_row_df.empty:
    st.error("Selected faculty not found in Faculty_Master.xlsx"); st.stop()

faculty_row     = faculty_row_df.iloc[0]
designation     = str(faculty_row["Designation"]).strip()
designation_key = designation.upper()
required_count  = DUTY_QUOTA.get(designation_key, 0)
if required_count == 0:
    st.warning("Designation rule not found. Verify designation values in Faculty_Master.xlsx.")

valuation_dates_list = valuation_dates_for_faculty(faculty_row)
valuation_set        = set(valuation_dates_list)

offline_options = offline_df[["Date","Session"]].drop_duplicates().sort_values(["Date","Session"]).copy()
offline_options["DateOnly"] = offline_options["Date"].dt.date
online_options  = online_df[["Date","Session"]].drop_duplicates().sort_values(["Date","Session"]).copy()
online_options["DateOnly"]  = online_options["Date"].dt.date

if designation_key == "P":
    selection_options = online_options;  selection_label = "Choose Online Date"
else:
    selection_options = offline_options; selection_label = "Choose Offline Date"

valid_dates = sorted([d for d in selection_options["DateOnly"].unique() if d not in valuation_set])

if st.session_state.selected_faculty != selected_clean:
    st.session_state.selected_faculty = selected_clean
    st.session_state.selected_slots   = []
    st.session_state.picked_date      = valid_dates[0] if valid_dates else None
if "picked_date" not in st.session_state:
    st.session_state.picked_date = valid_dates[0] if valid_dates else None

left, right = st.columns([1, 1.4])

with left:
    st.subheader("Willingness Selection")
    st.write(f"**Designation:** {designation}")
    st.write(f"**Options Required:** {required_count}")

    if designation_key == "ACP":
        acp_msg = ("Dear Sir, ACP faculty members will be given one online and one offline duty. "
                   "Please give all willingness for offline dates. We will fix online/offline accordingly.")
        st.info(acp_msg)
        if st.session_state.acp_notice_shown_for != selected_clean:
            st.session_state.acp_notice_shown_for = selected_clean
            st.toast(acp_msg, icon="ℹ️")

    if not valid_dates:
        st.warning(f"No selectable dates available after valuation blocking.")
    else:
        picked_date = st.selectbox(selection_label, valid_dates, key="picked_date",
                                   format_func=lambda d: d.strftime("%d-%m-%Y (%A)"))
        available   = set(selection_options[selection_options["DateOnly"]==picked_date]["Session"]
                          .dropna().astype(str).str.upper())
        btn1, btn2  = st.columns(2)
        with btn1:
            add_fn = st.button("Add FN", use_container_width=True,
                               disabled=("FN" not in available) or (len(st.session_state.selected_slots)>=required_count))
        with btn2:
            add_an = st.button("Add AN", use_container_width=True,
                               disabled=("AN" not in available) or (len(st.session_state.selected_slots)>=required_count))

        def add_slot(session):
            existing_dates = {item["Date"] for item in st.session_state.selected_slots}
            slot = {"Date": picked_date, "Session": session}
            if picked_date in valuation_set:
                st.warning("Valuation date cannot be selected.")
            elif picked_date in existing_dates:
                st.warning("FN and AN on the same date are not allowed.")
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
        selected_df = selected_df.sort_values(["Date","Session"]).copy().reset_index(drop=True)
        selected_df.insert(0,"Sl.No", selected_df.index+1)
        selected_df["Day"]  = pd.to_datetime(selected_df["Date"]).dt.day_name()
        selected_df["Date"] = pd.to_datetime(selected_df["Date"]).dt.strftime("%d-%m-%Y")
        st.dataframe(selected_df[["Sl.No","Date","Day","Session"]], use_container_width=True, hide_index=True)

        remove_sl = st.selectbox("Select Sl.No to remove", options=selected_df["Sl.No"].tolist())
        if st.button("Remove Selected Row", use_container_width=True):
            tr = selected_df[selected_df["Sl.No"]==remove_sl].iloc[0]
            td = pd.to_datetime(tr["Date"], dayfirst=True).date()
            ts = tr["Session"]
            st.session_state.selected_slots = [
                s for s in st.session_state.selected_slots
                if not (s["Date"]==td and s["Session"]==ts)
            ]

    willingness_df   = load_willingness()
    already_submitted = False
    if "FacultyClean" in willingness_df.columns:
        already_submitted = selected_clean in set(willingness_df["FacultyClean"].astype(str).tolist())

    st.markdown("### Submit Willingness")
    if already_submitted:
        st.warning("You have already submitted willingness.")

    remaining = max(required_count - len(st.session_state.selected_slots), 0)
    if already_submitted:
        st.info("Verification: Submission already exists for this faculty.")
    elif remaining == 0 and required_count > 0:
        st.success("Verification: Required willingness count completed. You can submit now.")
    else:
        st.info(f"Verification: Select {remaining} more option(s) to enable submission.")

    submit_disabled = already_submitted or len(st.session_state.selected_slots) != required_count
    if st.button("Submit Willingness", disabled=submit_disabled, use_container_width=True):
        new_rows = [{"Faculty": selected_name,
                     "Date":    item["Date"].strftime("%d-%m-%Y"),
                     "Session": item["Session"]}
                    for item in st.session_state.selected_slots]
        out_df = pd.concat([willingness_df.drop(columns=["FacultyClean"], errors="ignore"),
                            pd.DataFrame(new_rows)], ignore_index=True)
        out_df.to_excel(WILLINGNESS_FILE, index=False)
        st.toast("The University Examination Committee thanks you for submitting your willingness.", icon="✅")
        st.success(
            "The University Examination Committee thanks you for submitting your willingness. "
            "The final duty allocation will be carried out using AI-assisted optimization integrated "
            "with Google OR-Tools. Once finalized, it will be officially communicated. "
            "Kindly check this portal regularly for updates.")
        st.session_state.selected_slots = []

with right:
    if designation_key == "P":
        render_month_calendars(online_df, valuation_set, "Online Duty Calendar")
    else:
        render_month_calendars(offline_df, valuation_set, "Offline Duty Calendar")

st.markdown("---")
st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
