"""Streamlit faculty duty portal."""

import os
import streamlit as st
import pandas as pd


FACULTY_BASENAME = "Faculty_Master"
OFFLINE_BASENAME = "Offline_Duty"
ONLINE_BASENAME = "Online_Duty"
WILLINGNESS_BASENAME = "Willingness"
LOGO_FILE = "sastra_logo.png"


def clean(x):
    return str(x).strip().lower()


def to_date(value):
    return pd.to_datetime(value).date()


def find_file(basename):
    for ext in [".xlsx", ".xls", ".csv"]:
        fname = basename + ext
        if os.path.exists(fname):
            return fname
    return None


def read_file(uploaded, basename, required=True):
    if uploaded is not None:
        if uploaded.name.lower().endswith(".csv"):
            return pd.read_csv(uploaded)
        return pd.read_excel(uploaded)

    local_path = find_file(basename)
    if local_path:
        if local_path.endswith(".csv"):
            return pd.read_csv(local_path)
        return pd.read_excel(local_path)

    if required:
        st.error(f"Missing required file: {basename}.xlsx/.xls/.csv")
        st.stop()

    return pd.DataFrame()


# ---------------- PAGE CONFIG ---------------- #

st.set_page_config(page_title="SASTRA End Sem Duty Portal", layout="wide")

st.markdown("""
<style>
.main-title { text-align:center; font-size:36px; font-weight:800; color:#800000; }
.sub-title { text-align:center; font-size:22px; font-weight:600; color:#003366; }
.section-title { font-size:22px; font-weight:700; color:#003366; margin-top:6px; }
.simple-note { padding:10px; background:#fff3cd; border:1px solid #d1b35a; font-weight:600; }
</style>
""", unsafe_allow_html=True)


def header():
    if os.path.exists(LOGO_FILE):
        st.image(LOGO_FILE, use_container_width=True)
    st.markdown("<div class='main-title'>SASTRA SoME End Semester Examination Duty Portal</div>", unsafe_allow_html=True)
    st.markdown("<div class='sub-title'>School of Mechanical Engineering</div>", unsafe_allow_html=True)
    st.markdown("---")


# ---------------- SIDEBAR FILE UPLOAD ---------------- #

st.sidebar.header("Upload Data Files (Optional)")

faculty_upload = st.sidebar.file_uploader("Faculty_Master", type=["xlsx", "xls", "csv"])
offline_upload = st.sidebar.file_uploader("Offline_Duty", type=["xlsx", "xls", "csv"])
online_upload = st.sidebar.file_uploader("Online_Duty", type=["xlsx", "xls", "csv"])
willingness_upload = st.sidebar.file_uploader("Willingness (optional)", type=["xlsx", "xls", "csv"])


# ---------------- LOGIN ---------------- #

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    header()
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<div class='section-title'>Faculty Login</div>", unsafe_allow_html=True)
        user = st.text_input("Username")
        pwd = st.text_input("Password", type="password")

        if st.button("Login"):
            if user == "SASTRA" and pwd == "SASTRA":
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("Invalid Credentials")
    st.stop()


# ---------------- LOAD DATA ---------------- #

faculty_df = read_file(faculty_upload, FACULTY_BASENAME, True)
offline_df = read_file(offline_upload, OFFLINE_BASENAME, True)
online_df = read_file(online_upload, ONLINE_BASENAME, True)

faculty_df.columns = faculty_df.columns.str.strip()
offline_df.columns = offline_df.columns.str.strip()
online_df.columns = online_df.columns.str.strip()

faculty_df.rename(columns={faculty_df.columns[0]: "Name",
                           faculty_df.columns[1]: "Designation"}, inplace=True)

faculty_df["Clean"] = faculty_df["Name"].apply(clean)

offline_df.rename(columns={offline_df.columns[0]: "Date",
                           offline_df.columns[1]: "Session"}, inplace=True)

online_df.rename(columns={online_df.columns[0]: "Date",
                          online_df.columns[1]: "Session"}, inplace=True)

offline_df["Date"] = pd.to_datetime(offline_df["Date"], dayfirst=True)
online_df["Date"] = pd.to_datetime(online_df["Date"], dayfirst=True)

offline_df["Mode"] = "Offline"
online_df["Mode"] = "Online"

allocation_df = pd.concat([offline_df, online_df], ignore_index=True)


# ---------------- MAIN PAGE ---------------- #

header()

st.markdown("<div class='simple-note'>Official Notice: Willingness choices will be accommodated as much as possible.</div>", unsafe_allow_html=True)

selected = st.selectbox("Select Your Name", sorted(faculty_df["Name"].dropna().unique()))
selected_clean = clean(selected)

faculty_row = faculty_df[faculty_df["Clean"] == selected_clean]

designation = faculty_row.iloc[0]["Designation"]

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

col1, col2 = st.columns(2)

# ---------------- WILLINGNESS ---------------- #

with col1:
    st.markdown("<div class='section-title'>Willingness Selection</div>", unsafe_allow_html=True)
    st.write("Designation:", designation)
    st.write("Options Required:", required_count)

    choices = []
    for _, r in offline_df.iterrows():
        dt = to_date(r["Date"])
        choices.append(f"{dt.strftime('%d-%m-%Y')} | {r['Session']}")

    choices = sorted(set(choices))

    selected_slots = st.multiselect(
        f"Pick exactly {required_count} slots",
        choices
    )

    st.write("Selected:", len(selected_slots), "/", required_count)

    if st.button("Submit Willingness", disabled=len(selected_slots) != required_count):
        rows = []
        for item in selected_slots:
            date_txt, session = item.split("|")
            rows.append({"Faculty": selected,
                         "Date": date_txt.strip(),
                         "Session": session.strip()})

        out_df = pd.DataFrame(rows)
        out_df.to_excel("Willingness.xlsx", index=False)
        st.success("Willingness saved successfully.")


# ---------------- DUTY POOL ---------------- #

with col2:
    st.markdown("<div class='section-title'>Duty Date Pool</div>", unsafe_allow_html=True)
    allocation_df["Date"] = allocation_df["Date"].dt.date
    allocation_df["Day"] = pd.to_datetime(allocation_df["Date"]).dt.day_name()
    st.dataframe(allocation_df[["Date", "Day", "Session", "Mode"]],
                 use_container_width=True,
                 hide_index=True)


st.markdown("---")
st.markdown("Curated by Dr. N. Sathiya Narayanan, School of Mechanical Engineering")
