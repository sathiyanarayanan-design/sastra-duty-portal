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
    df = df.dropna(subset=["Date"])
    df["Session"] = df["Session"].astype(str).str.strip().str.upper()
    df["Required"] = pd.to_numeric(df["Required"], errors="coerce").fillna(1).astype(int)

    return df


def valuation_dates_for_faculty(row):
    dates = []
    for col in ["V1", "V2", "V3", "V4", "V5"]:
        if col in row.index and pd.notna(row[col]):
            dates.append(pd.to_datetime(row[col], dayfirst=True).date())
    return sorted(set(dates))


def demand_category(required, min_d, max_d):
    gap = (max_d - min_d) / 3 if max_d != min_d else 1
    low_max = round(min_d + gap)
    mid_max = round(min_d + 2 * gap)

    if required <= low_max:
        return "Low"
    if required <= mid_max:
        return "Medium"
    return "High"


def build_month_calendar_frame(duty_df, valuation_dates, year, month):
    duty_demand = duty_df.groupby("Date", as_index=False)["Required"].sum()
    demand_map = {
        d.date(): int(r) for d, r in zip(duty_demand["Date"], duty_demand["Required"])
    }

    month_start = pd.Timestamp(year=year, month=month, day=1)
    month_end = month_start + pd.offsets.MonthEnd(0)
    month_days = pd.date_range(month_start, month_end, freq="D")

    month_demands = [demand_map.get(dt.date(), 0) for dt in month_days]
    min_d = min(month_demands) if month_demands else 0
    max_d = max(month_demands) if month_demands else 1

    weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    rows = []
    for dt in month_days:
        req = demand_map.get(dt.date(), 0)

        if dt.date() in valuation_dates:
            category = "Valuation Locked"
        elif req == 0:
            category = "No Duty"
        else:
            category = demand_category(req, min_d, max_d)

        rows.append(
            {
                "Date": dt,
                "Week": dt.week,
                "Weekday": weekday_labels[dt.weekday()],
                "DayNum": dt.day,
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
        domain=["No Duty", "Low", "Medium", "High", "Valuation Locked"],
        range=["#ececec", "#2ca02c", "#ff9800", "#d62728", "#7b1fa2"],
    )

    for year, month in months:
        frame = build_month_calendar_frame(
            duty_df, set(valuation_dates), year, month
        )

        st.markdown(f"**{calmod.month_name[month]} {year}**")

        base = alt.Chart(frame).encode(
            x=alt.X(
                "Weekday:N",
                sort=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
                title="",
            ),
            y=alt.Y("week(Date):O", title=""),
            tooltip=[
                alt.Tooltip("DateLabel:N", title="Date"),
                alt.Tooltip("Required:Q", title="Demand"),
                alt.Tooltip("Category:N", title="Category"),
            ],
        )

        rect = base.mark_rect(stroke="white").encode(
            color=alt.Color("Category:N", scale=color_scale)
        )

        text = base.mark_text(color="black", fontSize=12).encode(text="DayNum:Q")

        st.altair_chart((rect + text).properties(height=250), use_container_width=True)


def load_willingness():
    if os.path.exists(WILLINGNESS_FILE):
        df = pd.read_excel(WILLINGNESS_FILE)
        df["FacultyClean"] = df["Faculty"].apply(clean)
        return df
    return pd.DataFrame(columns=["Faculty", "Date", "Session", "FacultyClean"])


# ---------------- LOGIN ---------------- #
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("Faculty Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if username == "SASTRA" and password == "SASTRA":
            st.session_state.logged_in = True
            st.rerun()
        else:
            st.error("Invalid credentials")

    st.stop()

# ---------------- LOAD DATA ---------------- #
faculty_df = load_excel(FACULTY_FILE)
offline_df = normalize_duty_df(load_excel(OFFLINE_FILE))
online_df = normalize_duty_df(load_excel(ONLINE_FILE))

faculty_df.rename(
    columns={
        faculty_df.columns[0]: "Name",
        faculty_df.columns[1]: "Designation",
    },
    inplace=True,
)

faculty_df["Clean"] = faculty_df["Name"].apply(clean)

# ---------------- HEADER ---------------- #
if os.path.exists(LOGO_FILE):
    st.image(LOGO_FILE, use_container_width=True)

st.markdown("## SASTRA SoME End Semester Examination Duty Portal")
st.markdown("### School of Mechanical Engineering")
st.markdown("---")
st.info("Official Notice: Willingness will be accommodated as much as possible.")

# ---------------- FACULTY SELECT ---------------- #
selected_name = st.selectbox(
    "Select Your Name",
    sorted(faculty_df["Name"].dropna().unique()),
)

selected_clean = clean(selected_name)
faculty_row = faculty_df[faculty_df["Clean"] == selected_clean].iloc[0]
designation = str(faculty_row["Designation"]).strip()

duty_structure = {
    "P": 3,
    "ACP": 5,
    "SAP": 7,
    "AP3": 7,
    "AP2": 7,
    "TA": 9,
    "RA": 9,
}

required_count = duty_structure.get(designation, 0)
valuation_dates = valuation_dates_for_faculty(faculty_row)
valuation_set = set(valuation_dates)

if "selected_slots" not in st.session_state:
    st.session_state.selected_slots = []

left, right = st.columns([1, 1.4])

with left:
    st.subheader("Willingness Selection")
    st.write("Designation:", designation)
    st.write("Options Required:", required_count)

    if valuation_dates:
        st.write("Blocked Dates:", valuation_dates)

with right:
    render_month_calendars(offline_df, valuation_set, "Offline Duty Calendar")

    if designation in {"P", "ACP"}:
        render_month_calendars(online_df, valuation_set, "Online Duty Calendar")

st.markdown("---")
st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
