import os
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


def load_excel(path):
    if not os.path.exists(path):
        st.error(f"{path} not found in repository.")
        st.stop()
    return pd.read_excel(path)


def normalize_duty_df(df):
    df = df.copy()
    df.columns = df.columns.str.strip()

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


def render_heatmap(duty_df, valuation_set, title):
    st.subheader(title)

    demand = duty_df.groupby("Date", as_index=False)["Required"].sum()

    min_d = demand["Required"].min()
    max_d = demand["Required"].max()
    gap = (max_d - min_d) / 3 if max_d != min_d else 1
    low_max = round(min_d + gap)
    mid_max = round(min_d + 2 * gap)

    def category(row):
        dt = row["Date"].date()
        if dt in valuation_set:
            return "Valuation Locked"
        if row["Required"] <= low_max:
            return "Low"
        if row["Required"] <= mid_max:
            return "Medium"
        return "High"

    demand["Category"] = demand.apply(category, axis=1)
    demand["Day"] = demand["Date"].dt.day
    demand["Month"] = demand["Date"].dt.strftime("%b-%Y")

    chart = (
        alt.Chart(demand)
        .mark_rect(stroke="white")
        .encode(
            x=alt.X("day(Date):O", title="Day"),
            y=alt.Y("yearmonth(Date):O", title="Month"),
            color=alt.Color(
                "Category:N",
                scale=alt.Scale(
                    domain=["Low", "Medium", "High", "Valuation Locked"],
                    range=["#2ca02c", "#ff9800", "#d62728", "#7b1fa2"],
                ),
            ),
            tooltip=["Date:T", "Required:Q", "Category:N"],
        )
        .properties(height=250)
    )

    st.altair_chart(chart, use_container_width=True)


def load_willingness():
    if os.path.exists(WILLINGNESS_FILE):
        return pd.read_excel(WILLINGNESS_FILE)
    return pd.DataFrame(columns=["Faculty", "Date", "Session"])


# ---------------- LOAD DATA ---------------- #

faculty_df = load_excel(FACULTY_FILE)
offline_df = normalize_duty_df(load_excel(OFFLINE_FILE))
online_df = normalize_duty_df(load_excel(ONLINE_FILE))

faculty_df.columns = faculty_df.columns.str.strip()
faculty_df.rename(columns={
    faculty_df.columns[0]: "Name",
    faculty_df.columns[1]: "Designation"
}, inplace=True)

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
    sorted(faculty_df["Name"].dropna().unique())
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
    "RA": 9
}

required_count = duty_structure.get(designation, 0)

valuation_dates = valuation_dates_for_faculty(faculty_row)
valuation_set = set(valuation_dates)

if "selected_slots" not in st.session_state:
    st.session_state.selected_slots = []


# ---------------- LAYOUT ---------------- #

left, right = st.columns([1, 1.3])

with left:
    st.subheader("Willingness Selection")
    st.write("Designation:", designation)
    st.write("Options Required:", required_count)

    if valuation_dates:
        st.write("Blocked Valuation Dates:", valuation_dates)

    options_df = offline_df[["Date", "Session"]].drop_duplicates()
    options_df["DateOnly"] = options_df["Date"].dt.date

    valid_dates = sorted([d for d in options_df["DateOnly"].unique() if d not in valuation_set])

    if valid_dates:
        chosen_date = st.selectbox(
            "Choose Date",
            valid_dates,
            format_func=lambda d: d.strftime("%d-%m-%Y (%A)")
        )

        sessions = options_df[options_df["DateOnly"] == chosen_date]["Session"].unique()
        chosen_session = st.selectbox("Choose Session", sorted(sessions))

        if st.button("Add Slot") and len(st.session_state.selected_slots) < required_count:
            existing_dates = {x["Date"] for x in st.session_state.selected_slots}
            if chosen_date not in existing_dates:
                st.session_state.selected_slots.append({
                    "Date": chosen_date,
                    "Session": chosen_session
                })

    st.write("Selected:", len(st.session_state.selected_slots), "/", required_count)

    if st.session_state.selected_slots:
        st.dataframe(pd.DataFrame(st.session_state.selected_slots))

    willingness_df = load_willingness()
    already_submitted = selected_name in willingness_df.get("Faculty", [])

    if already_submitted:
        st.warning("You have already submitted willingness.")

    if st.button("Submit Willingness",
                 disabled=already_submitted or len(st.session_state.selected_slots) != required_count):

        rows = [{
            "Faculty": selected_name,
            "Date": item["Date"].strftime("%d-%m-%Y"),
            "Session": item["Session"]
        } for item in st.session_state.selected_slots]

        out_df = pd.concat([willingness_df, pd.DataFrame(rows)], ignore_index=True)
        out_df.to_excel(WILLINGNESS_FILE, index=False)

        st.success("Willingness submitted successfully!")
        st.session_state.selected_slots = []


with right:
    render_heatmap(offline_df, valuation_set, "Offline Duty Heat Map")

    if designation in {"P", "ACP"}:
        render_heatmap(online_df, valuation_set, "Online Duty Heat Map")


st.markdown("---")
st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
