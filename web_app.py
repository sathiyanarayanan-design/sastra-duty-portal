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
        st.error("Duty file must contain Date, Session, Required columns.")
        st.stop()

    df.rename(columns={
        df.columns[0]: "Date",
        df.columns[1]: "Session",
        df.columns[2]: "Required"
    }, inplace=True)

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


def demand_category(req, min_d, max_d):
    if max_d == min_d:
        return "Medium"

    gap = (max_d - min_d) / 3
    if req <= min_d + gap:
        return "Low"
    elif req <= min_d + 2 * gap:
        return "Medium"
    else:
        return "High"


def build_calendar(duty_df, valuation_dates, year, month):
    duty_sum = duty_df.groupby("Date")["Required"].sum().reset_index()
    demand_map = {d.date(): r for d, r in zip(duty_sum["Date"], duty_sum["Required"])}

    start = pd.Timestamp(year=year, month=month, day=1)
    end = start + pd.offsets.MonthEnd(0)
    days = pd.date_range(start, end)

    min_d = min(demand_map.values()) if demand_map else 0
    max_d = max(demand_map.values()) if demand_map else 1

    rows = []
    for d in days:
        date_only = d.date()
        req = demand_map.get(date_only, 0)

        if date_only in valuation_dates:
            cat = "Valuation Locked"
        elif req == 0:
            cat = "No Duty"
        else:
            cat = demand_category(req, min_d, max_d)

        rows.append({
            "Date": d,
            "Day": d.day,
            "Weekday": d.strftime("%a"),
            "Week": (d.day + start.weekday() - 1) // 7 + 1,
            "Required": req,
            "Category": cat
        })

    return pd.DataFrame(rows)


def render_calendar(duty_df, valuation_dates, title):
    st.subheader(title)

    months = sorted({(d.year, d.month) for d in duty_df["Date"]})

    color_scale = alt.Scale(
        domain=["No Duty", "Low", "Medium", "High", "Valuation Locked"],
        range=["#eeeeee", "#4caf50", "#ff9800", "#f44336", "#7b1fa2"]
    )

    for year, month in months:
        frame = build_calendar(duty_df, valuation_dates, year, month)

        st.markdown(f"**{calmod.month_name[month]} {year}**")

        base = alt.Chart(frame).encode(
            x=alt.X("Weekday:N",
                    sort=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"],
                    title=""),
            y=alt.Y("Week:O", title="")
        )

        rect = base.mark_rect().encode(
            color=alt.Color("Category:N", scale=color_scale,
                            legend=alt.Legend(title="Heat Map Legend"))
        )

        text = base.mark_text(color="black").encode(text="Day:Q")

        st.altair_chart((rect + text).properties(height=220),
                        use_container_width=True)


def load_willingness():
    if os.path.exists(WILLINGNESS_FILE):
        df = pd.read_excel(WILLINGNESS_FILE)
        if "Faculty" not in df.columns:
            df["Faculty"] = ""
        df["FacultyClean"] = df["Faculty"].apply(clean)
        return df
    return pd.DataFrame(columns=["Faculty", "Date", "Session", "FacultyClean"])


# ---------------- LOGIN ---------------- #
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("SASTRA SoME End Semester Duty Portal")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        if username == "SASTRA" and password == "SASTRA":
            st.session_state.logged_in = True
            st.rerun()
        else:
            st.error("Invalid Credentials")
    st.stop()


# ---------------- LOAD DATA ---------------- #
faculty_df = load_excel(FACULTY_FILE)
offline_df = normalize_duty_df(load_excel(OFFLINE_FILE))
online_df = normalize_duty_df(load_excel(ONLINE_FILE))

faculty_df.rename(columns={
    faculty_df.columns[0]: "Name",
    faculty_df.columns[1]: "Designation"
}, inplace=True)

faculty_df["Clean"] = faculty_df["Name"].apply(clean)

# ---------------- MAIN ---------------- #
st.title("SASTRA SoME End Semester Examination Portal")
st.info("Willingness will be accommodated as per institutional requirements.")

selected = st.selectbox("Select Your Name",
                        sorted(faculty_df["Name"].unique()))

selected_clean = clean(selected)
row = faculty_df[faculty_df["Clean"] == selected_clean].iloc[0]

designation = row["Designation"]

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
valuation_dates = valuation_dates_for_faculty(row)

st.write(f"**Designation:** {designation}")
st.write(f"**Options Required:** {required_count}")
st.write(f"**Blocked (Valuation):** {valuation_dates if valuation_dates else 'None'}")


# ---------------- CALENDAR DISPLAY ---------------- #
col1, col2 = st.columns(2)

with col1:
    render_calendar(offline_df, set(valuation_dates),
                    "Offline Duty Calendar")

with col2:
    if designation in {"P", "ACP"}:
        render_calendar(online_df, set(valuation_dates),
                        "Online Duty Calendar")


# ---------------- FOOTER ---------------- #
st.markdown("---")
st.markdown(
    "Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering"
)
