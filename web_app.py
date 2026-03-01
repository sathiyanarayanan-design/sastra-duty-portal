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

# ---------------- HELPER FUNCTIONS ---------------- #

def clean(x):
    return str(x).strip().lower()


def load_excel(path):
    if not os.path.exists(path):
        st.error(f"{path} not found in repository.")
        st.stop()
    return pd.read_excel(path)


def normalize_duty_df(df):
    df = df.copy()
    df.columns = df.columns.str.strip()

    if len(df.columns) < 3:
        st.error("Duty files must contain Date, Session, Required columns.")
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


def load_willingness():
    if os.path.exists(WILLINGNESS_FILE):
        df = pd.read_excel(WILLINGNESS_FILE)
        if "Faculty" in df.columns:
            df["FacultyClean"] = df["Faculty"].apply(clean)
        else:
            df["FacultyClean"] = ""
        return df
    return pd.DataFrame(columns=["Faculty", "Date", "Session", "FacultyClean"])


# ---------------- LOGIN ---------------- #

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    st.title("SASTRA SoME Faculty Login")
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

faculty_df.columns = faculty_df.columns.str.strip()

if len(faculty_df.columns) < 2:
    st.error("Faculty_Master.xlsx must contain Name and Designation columns.")
    st.stop()

faculty_df.rename(
    columns={
        faculty_df.columns[0]: "Name",
        faculty_df.columns[1]: "Designation"
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
st.info("Official Notice: Willingness will be accommodated as much as possible based on institutional requirements.")

# ---------------- FACULTY SELECTION ---------------- #

selected_name = st.selectbox(
    "Select Your Name",
    sorted(faculty_df["Name"].dropna().unique())
)

selected_clean = clean(selected_name)
faculty_row = faculty_df[faculty_df["Clean"] == selected_clean].iloc[0]
designation = str(faculty_row["Designation"]).strip()

# ---------------- DUTY STRUCTURE ---------------- #

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

offline_options = offline_df[["Date", "Session"]].drop_duplicates().sort_values(["Date", "Session"])
offline_options["DateOnly"] = offline_options["Date"].dt.date
valid_dates = sorted([d for d in offline_options["DateOnly"].unique() if d not in valuation_set])

if "selected_slots" not in st.session_state:
    st.session_state.selected_slots = []

# ---------------- LAYOUT ---------------- #

left, right = st.columns([1, 1.4])

# ---------------- LEFT PANEL ---------------- #

with left:
    st.subheader("Willingness Selection")
    st.write(f"**Designation:** {designation}")
    st.write(f"**Options Required:** {required_count}")

    if valuation_dates:
        st.write("Blocked Dates:", ", ".join(d.strftime("%d-%m-%Y") for d in valuation_dates))

    if valid_dates:
        picked_date = st.selectbox(
            "Choose Offline Date",
            valid_dates,
            format_func=lambda d: d.strftime("%d-%m-%Y (%A)")
        )

        available_sessions = offline_options[
            offline_options["DateOnly"] == picked_date
        ]["Session"].unique()

        col1, col2 = st.columns(2)

        if col1.button("Add FN"):
            if "FN" in available_sessions:
                existing_dates = {x["Date"] for x in st.session_state.selected_slots}
                if picked_date not in existing_dates:
                    st.session_state.selected_slots.append({"Date": picked_date, "Session": "FN"})

        if col2.button("Add AN"):
            if "AN" in available_sessions:
                existing_dates = {x["Date"] for x in st.session_state.selected_slots}
                if picked_date not in existing_dates:
                    st.session_state.selected_slots.append({"Date": picked_date, "Session": "AN"})

    st.session_state.selected_slots = st.session_state.selected_slots[:required_count]

    st.write(f"**Selected:** {len(st.session_state.selected_slots)} / {required_count}")

    if st.session_state.selected_slots:
        display_df = pd.DataFrame(st.session_state.selected_slots)
        display_df["Date"] = pd.to_datetime(display_df["Date"]).dt.strftime("%d-%m-%Y")
        st.dataframe(display_df, use_container_width=True)

    willingness_df = load_willingness()
    already_submitted = selected_clean in set(willingness_df["FacultyClean"].tolist())

    if already_submitted:
        st.warning("You have already submitted willingness.")

    if st.button("Submit Willingness",
                 disabled=already_submitted or len(st.session_state.selected_slots) != required_count):

        new_rows = [
            {
                "Faculty": selected_name,
                "Date": item["Date"].strftime("%d-%m-%Y"),
                "Session": item["Session"]
            }
            for item in st.session_state.selected_slots
        ]

        out_df = pd.concat(
            [willingness_df.drop(columns=["FacultyClean"], errors="ignore"),
             pd.DataFrame(new_rows)],
            ignore_index=True
        )

        out_df.to_excel(WILLINGNESS_FILE, index=False)

        st.success("Willingness submitted successfully!")
        st.session_state.selected_slots = []

# ---------------- RIGHT PANEL ---------------- #

with right:
    st.subheader("Offline Duty Demand Heatmap")

    demand = offline_df.groupby("Date", as_index=False)["Required"].sum()
    demand["Day"] = demand["Date"].dt.day
    demand["Month"] = demand["Date"].dt.strftime("%b-%Y")

    chart = alt.Chart(demand).mark_rect(stroke="white").encode(
        x=alt.X("day(Date):O", title="Day"),
        y=alt.Y("yearmonth(Date):O", title="Month"),
        color=alt.Color("Required:Q", scale=alt.Scale(scheme="reds")),
        tooltip=["Date:T", "Required:Q"]
    ).properties(height=250)

    st.altair_chart(chart, use_container_width=True)

st.markdown("---")
st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
