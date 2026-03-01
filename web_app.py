import os
import calendar as calmod
import pandas as pd
import streamlit as st
import altair as alt

# ---------------- CONFIG ---------------- #
FACULTY_FILE = "Faculty_Master.xlsx"
OFFLINE_FILE = "Offline_Duty.xlsx"
ONLINE_FILE = "Online_Duty.xlsx"
WILLINGNESS_FILE = "Willingness.xlsx"
LOGO_FILE = "sastra_logo.png"

st.set_page_config(page_title="SASTRA Duty Portal", layout="wide")


# ---------------- FUNCTIONS ---------------- #
def clean(x):
    return str(x).strip().lower()


def normalize_session(value):
    text = str(value).strip().upper()
    if text in {"FN", "FORENOON", "MORNING", "AM"}:
        return "FN"
    if text in {"AN", "AFTERNOON", "EVENING", "PM"}:
        return "AN"
    return text


def load_excel(file_path):
    if not os.path.exists(file_path):
        st.error(f"{file_path} not found in repository.")
        st.stop()
    return pd.read_excel(file_path)


def normalize_duty_df(df):
    df = df.copy()
    df.columns = df.columns.str.strip()
    if len(df.columns) < 3:
        st.error("Duty files must include Date, Session, and Required columns.")
        st.stop()

    df.rename(
        columns={
            df.columns[0]: "Date",
            df.columns[1]: "Session",
            df.columns[2]: "Required",
        },
        inplace=True,
    )
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["Date"]).copy()
    df["Session"] = df["Session"].apply(normalize_session)
    df["Required"] = pd.to_numeric(df["Required"], errors="coerce").fillna(1).astype(int)
    return df


def valuation_dates_for_faculty(faculty_row):
    dates = []
    for col in ["V1", "V2", "V3", "V4", "V5"]:
        if col in faculty_row.index and pd.notna(faculty_row[col]):
            dates.append(pd.to_datetime(faculty_row[col], dayfirst=True).date())
    return sorted(set(dates))


def demand_category(required):
    if required < 3:
        return "Low (<3)"
    if 3 <= required <= 7:
        return "Medium (3-7)"
    return "High (>7)"


def build_month_calendar_frame(duty_df, valuation_dates, year, month):
    session_demand = duty_df.groupby(["Date", "Session"], as_index=False)["Required"].sum()
    demand_map = {
        (d.date(), str(sess).upper()): int(req)
        for d, sess, req in zip(session_demand["Date"], session_demand["Session"], session_demand["Required"])
    }

    month_start = pd.Timestamp(year=year, month=month, day=1)
    month_end = month_start + pd.offsets.MonthEnd(0)
    month_days = pd.date_range(month_start, month_end, freq="D")
    first_weekday = month_start.weekday()  # Mon=0
    weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    rows = []
    for dt in month_days:
        week_no = ((dt.day + first_weekday - 1) // 7) + 1
        date_only = dt.date()
        for session in ["FN", "AN"]:
            req = demand_map.get((date_only, session), 0)
            if date_only in valuation_dates:
                category = "Valuation Locked"
            elif req == 0:
                category = "No Duty"
            else:
                category = demand_category(req)

            rows.append(
                {
                    "Date": dt,
                    "Week": week_no,
                    "Weekday": weekday_labels[dt.weekday()],
                    "DayNum": dt.day,
                    "Session": session,
                    "Required": req,
                    "Category": category,
                    "DateLabel": dt.strftime("%d-%m-%Y"),
                }
            )
    return pd.DataFrame(rows)


def render_month_calendars(duty_df, valuation_dates, title):
    st.markdown(f"#### {title}")
    months = sorted({(d.year, d.month) for d in duty_df["Date"]})

    color_scale = alt.Scale(
        domain=["No Duty", "Low (<3)", "Medium (3-7)", "High (>7)", "Valuation Locked"],
        range=["#ececec", "#2ca02c", "#f1c40f", "#d62728", "#ff69b4"],
    )

    st.markdown(
        "**Heat Map Legend:** "
        "⬜ No Duty  "
        "🟩 Low (<3)  "
        "🟨 Medium (3-7)  "
        "🟥 High (>7)  "
        "🩷 Valuation Locked"
    )

    for year, month in months:
        frame = build_month_calendar_frame(duty_df, set(valuation_dates), year, month)
        high_count = int((frame["Category"] == "High (>7)").sum())
        st.markdown(f"**{calmod.month_name[month]} {year}**")
        st.caption(f"High-demand session slots (>7): {high_count}")

        base = alt.Chart(frame).encode(
            x=alt.X("Weekday:N", sort=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], title=""),
            xOffset=alt.XOffset("Session:N", sort=["FN", "AN"], title=""),
            y=alt.Y("Week:O", sort="ascending", title=""),
            tooltip=[
                alt.Tooltip("DateLabel:N", title="Date"),
                alt.Tooltip("Session:N", title="Session"),
                alt.Tooltip("Required:Q", title="Demand"),
                alt.Tooltip("Category:N", title="Category"),
            ],
        )

        rect = base.mark_rect(stroke="white").encode(
            color=alt.Color("Category:N", scale=color_scale, legend=alt.Legend(title="Heat Map Legend"))
        )

        day_text = (
            alt.Chart(frame[frame["Session"] == "FN"])
            .mark_text(color="black", fontSize=11, dy=-6)
            .encode(
                x=alt.X("Weekday:N", sort=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
                y=alt.Y("Week:O", sort="ascending"),
                text=alt.Text("DayNum:Q"),
            )
        )

        st.altair_chart((rect + day_text).properties(height=230), use_container_width=True)
        st.caption("Each date is split into two halves: left = FN, right = AN.")


def load_willingness():
    if os.path.exists(WILLINGNESS_FILE):
        df = pd.read_excel(WILLINGNESS_FILE)
        if "Faculty" not in df.columns:
            df["Faculty"] = ""
        df["FacultyClean"] = df["Faculty"].apply(clean)
        return df
    return pd.DataFrame(columns=["Faculty", "Date", "Session", "FacultyClean"])


def render_branding_header(show_logo=True):
    if show_logo and os.path.exists(LOGO_FILE):
        st.image(LOGO_FILE, use_container_width=True)

    st.markdown("## SASTRA SoME End Semester Examination Duty Portal")
    st.markdown("### School of Mechanical Engineering")
    st.markdown("---")


# ---------------- LOGIN ---------------- #
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    render_branding_header(show_logo=True)
    st.info("Official Notice: Willingness will be accommodated as much as possible based on institutional requirements.")
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.subheader("Faculty Login")
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Login"):
            if username == "SASTRA" and password == "SASTRA":
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("Invalid credentials")
    st.markdown("---")
    st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()

if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False


# ---------------- LOAD DATA ---------------- #
faculty_df = load_excel(FACULTY_FILE)
offline_df = normalize_duty_df(load_excel(OFFLINE_FILE))
online_df = normalize_duty_df(load_excel(ONLINE_FILE))

faculty_df.columns = faculty_df.columns.str.strip()
if len(faculty_df.columns) < 2:
    st.error("Faculty_Master.xlsx must include Name and Designation columns.")
    st.stop()

faculty_df.rename(columns={faculty_df.columns[0]: "Name", faculty_df.columns[1]: "Designation"}, inplace=True)
faculty_df["Clean"] = faculty_df["Name"].apply(clean)

# ---------------- HEADER ---------------- #
render_branding_header(show_logo=False)

st.markdown(
    """
    <style>
    .blink-notice {
        font-weight: 700;
        color: #800000;
        padding: 10px 12px;
        border: 2px solid #800000;
        background: #fff6f6;
        border-radius: 6px;
        animation: blinkPulse 1.2s infinite;
    }
    @keyframes blinkPulse {
        0% { opacity: 1; }
        50% { opacity: 0.35; }
        100% { opacity: 1; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    "<div class='blink-notice'>Official Notice: The University Examination Committee sincerely appreciates your cooperation. Every effort will be made to accommodate your willingness, while ensuring adherence to institutional requirements and examination needs. The final duty allocation will be carried out using AI-assisted optimization integrated with Google OR-Tools.</div>",
    unsafe_allow_html=True,
)

if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False
if "panel_mode" not in st.session_state:
    st.session_state.panel_mode = "User View"
if "confirm_delete_willingness" not in st.session_state:
    st.session_state.confirm_delete_willingness = False
if "selected_slots" not in st.session_state:
    st.session_state.selected_slots = []
if "selected_faculty" not in st.session_state:
    st.session_state.selected_faculty = ""

# Control panel at top as requested
st.subheader("Control Panel")
panel_mode = st.radio(
    "Choose Mode",
    ["User View", "Admin View"],
    horizontal=True,
    key="panel_mode",
)

if panel_mode == "Admin View":
    st.markdown("### Admin View (Password Protected)")
    if not st.session_state.admin_authenticated:
        admin_pass = st.text_input("Admin Password", type="password", key="admin_password")
        if st.button("Unlock Admin View", key="unlock_admin"):
            if admin_pass == "sathya":
                st.session_state.admin_authenticated = True
                st.success("Admin access granted.")
                st.rerun()
            else:
                st.error("Invalid admin password.")
    else:
        st.success("Admin view unlocked")
        willingness_admin = load_willingness().drop(columns=["FacultyClean"], errors="ignore")
        if willingness_admin.empty:
            st.info("No willingness submissions yet.")
        else:
            view_df = willingness_admin.copy().reset_index(drop=True)
            view_df.insert(0, "Sl.No", view_df.index + 1)
            st.dataframe(view_df, use_container_width=True, hide_index=True)
            csv_data = view_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download Willingness CSV",
                data=csv_data,
                file_name="Willingness_Admin_View.csv",
                mime="text/csv",
                key="download_willingness_csv",
            )

        st.markdown("#### Delete Filled Willingness")
        st.checkbox(
            "I confirm deletion of all submitted willingness records",
            key="confirm_delete_willingness",
        )
        if st.button("Delete All Willingness", key="delete_all_willingness", type="primary"):
            if st.session_state.confirm_delete_willingness:
                empty_df = pd.DataFrame(columns=["Faculty", "Date", "Session"])
                empty_df.to_excel(WILLINGNESS_FILE, index=False)
                st.success("All willingness records deleted.")
                st.session_state.confirm_delete_willingness = False
                st.rerun()
            else:
                st.error("Please confirm deletion before proceeding.")

        if st.button("Lock Admin View", key="lock_admin"):
            st.session_state.admin_authenticated = False
            st.success("Admin view locked.")
            st.rerun()

    st.markdown("---")
    st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()

# ---------------- FACULTY SELECT ---------------- #
selected_name = st.selectbox("Select Your Name", sorted(faculty_df["Name"].dropna().unique()))
selected_clean = clean(selected_name)
faculty_row_df = faculty_df[faculty_df["Clean"] == selected_clean]
if faculty_row_df.empty:
    st.error("Selected faculty not found in Faculty_Master.xlsx")
    st.stop()

faculty_row = faculty_row_df.iloc[0]
designation = str(faculty_row["Designation"]).strip()
designation_key = designation.upper()

duty_structure = {
    "P": 3,
    "ACP": 5,
    "SAP": 7,
    "AP3": 7,
    "AP2": 7,
    "TA": 9,
    "RA": 9,
}
required_count = duty_structure.get(designation_key, 0)
if required_count == 0:
    st.warning("Designation rule not found. Please verify designation values in Faculty_Master.xlsx.")

valuation_dates = valuation_dates_for_faculty(faculty_row)
valuation_set = set(valuation_dates)

offline_options = offline_df[["Date", "Session"]].drop_duplicates().sort_values(["Date", "Session"])
offline_options["DateOnly"] = offline_options["Date"].dt.date
valid_dates = sorted([d for d in offline_options["DateOnly"].unique() if d not in valuation_set])

if st.session_state.selected_faculty != selected_clean:
    st.session_state.selected_faculty = selected_clean
    st.session_state.selected_slots = []
    st.session_state.picked_date = valid_dates[0] if valid_dates else None
if "picked_date" not in st.session_state:
    st.session_state.picked_date = valid_dates[0] if valid_dates else None

left, right = st.columns([1, 1.4])

with left:
    st.subheader("Willingness Selection")
    st.write(f"**Designation:** {designation}")
    st.write(f"**Options Required:** {required_count}")

    if not valid_dates:
        st.warning("No selectable offline dates available after valuation blocking.")
    else:
        picked_date = st.selectbox(
            "Choose Offline Date",
            valid_dates,
            key="picked_date",
            format_func=lambda d: d.strftime("%d-%m-%Y (%A)"),
        )

        available = set(offline_options[offline_options["DateOnly"] == picked_date]["Session"].dropna().astype(str).str.upper())
        btn1, btn2 = st.columns(2)
        with btn1:
            add_fn = st.button("Add FN", use_container_width=True, disabled=("FN" not in available) or (len(st.session_state.selected_slots) >= required_count))
        with btn2:
            add_an = st.button("Add AN", use_container_width=True, disabled=("AN" not in available) or (len(st.session_state.selected_slots) >= required_count))

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

        if add_fn:
            add_slot("FN")
        if add_an:
            add_slot("AN")

    st.session_state.selected_slots = st.session_state.selected_slots[:required_count]
    st.write(f"**Selected:** {len(st.session_state.selected_slots)} / {required_count}")

    selected_df = pd.DataFrame(st.session_state.selected_slots)
    if not selected_df.empty:
        selected_df = selected_df.sort_values(["Date", "Session"]).copy().reset_index(drop=True)
        selected_df.insert(0, "Sl.No", selected_df.index + 1)
        selected_df["Day"] = pd.to_datetime(selected_df["Date"]).dt.day_name()
        selected_df["Date"] = pd.to_datetime(selected_df["Date"]).dt.strftime("%d-%m-%Y")
        st.dataframe(selected_df[["Sl.No", "Date", "Day", "Session"]], use_container_width=True, hide_index=True)

        remove_sl = st.selectbox("Select Sl.No to remove", options=selected_df["Sl.No"].tolist(), format_func=lambda x: f"{x}")
        if st.button("Remove Selected Row", use_container_width=True):
            target_row = selected_df[selected_df["Sl.No"] == remove_sl].iloc[0]
            target_date = pd.to_datetime(target_row["Date"], dayfirst=True).date()
            target_session = target_row["Session"]
            st.session_state.selected_slots = [
                s for s in st.session_state.selected_slots
                if not (s["Date"] == target_date and s["Session"] == target_session)
            ]

    willingness_df = load_willingness()
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
    submitted = st.button("Submit Willingness", disabled=submit_disabled, use_container_width=True)
    if submitted:
        new_rows = [
            {"Faculty": selected_name, "Date": item["Date"].strftime("%d-%m-%Y"), "Session": item["Session"]}
            for item in st.session_state.selected_slots
        ]
        out_df = pd.concat([willingness_df.drop(columns=["FacultyClean"], errors="ignore"), pd.DataFrame(new_rows)], ignore_index=True)
        out_df.to_excel(WILLINGNESS_FILE, index=False)
        st.toast("The University Examination Committee thanks you for submitting your willingness.", icon="✅")
        st.success(
            "The University Examination Committee thanks you for submitting your willingness. "
            "The final duty allocation will be carried out using AI-assisted optimization integrated with Google OR-Tools. "
            "Once finalized, the allocation will be officially communicated. Kindly check this portal regularly for updates."
        )
        st.session_state.selected_slots = []

with right:
    render_month_calendars(offline_df, valuation_set, "Offline Duty Calendar")
    if designation_key in {"P", "ACP"}:
        render_month_calendars(online_df, valuation_set, "Online Duty Calendar")

st.markdown("---")
st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
