"""Streamlit faculty duty portal."""

import os
import streamlit as st
import pandas as pd

FACULTY_FILE = "Faculty_Master.xlsx"
ALLOCATION_FILE = "Final_Allocation.xlsx"
WILLINGNESS_FILE = "Willingness.xlsx"
LOGO_FILE = "sastra_logo.png"


def clean(x):
    return str(x).strip().lower()


def to_date(value):
    return pd.to_datetime(value).date()


st.set_page_config(page_title="SASTRA End Sem Duty Portal", layout="wide")

st.markdown(
    """
<style>
.main-title { text-align:center; font-size:36px; font-weight:800; color:#800000; }
.sub-title { text-align:center; font-size:22px; font-weight:600; color:#003366; }
.section-title { font-size:22px; font-weight:700; color:#003366; margin-top:6px; }
.simple-note { padding:10px; background-color:#fff3cd; border:1px solid #d1b35a; font-weight:600; }
</style>
""",
    unsafe_allow_html=True,
)


def header_section():
    if os.path.exists(LOGO_FILE):
        st.image(LOGO_FILE, use_container_width=True)
    st.markdown("<div class='main-title'>SASTRA SoME End Semester Examination Duty Portal</div>", unsafe_allow_html=True)
    st.markdown("<div class='sub-title'>School of Mechanical Engineering</div>", unsafe_allow_html=True)
    st.markdown("---")


# ---------------- LOGIN ---------------- #

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    header_section()
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("<div class='section-title'>Faculty Login</div>", unsafe_allow_html=True)
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

if not os.path.exists(FACULTY_FILE) or not os.path.exists(ALLOCATION_FILE):
    st.error("Required Excel files are missing in repository.")
    st.stop()

faculty_df = pd.read_excel(FACULTY_FILE)
allocation_df = pd.read_excel(ALLOCATION_FILE)

faculty_df.columns = faculty_df.columns.str.strip()
allocation_df.columns = allocation_df.columns.str.strip()

faculty_df["Clean"] = faculty_df.iloc[:, 0].apply(clean)
allocation_df["Faculty"] = allocation_df["Faculty"].apply(clean)
allocation_df["Date"] = pd.to_datetime(allocation_df["Date"])
allocation_df["Session"] = allocation_df["Session"].astype(str).str.upper()
allocation_df["Mode"] = allocation_df["Mode"].astype(str).str.title()

if "selected_slots" not in st.session_state:
    st.session_state.selected_slots = []

header_section()

st.markdown(
    "<div class='simple-note'>Official Notice: Willingness choices will be accommodated as much as possible. Final allocation may vary based on institutional requirements.</div>",
    unsafe_allow_html=True,
)

selected = st.selectbox("Select Your Name", sorted(faculty_df.iloc[:, 0]))
selected_clean = clean(selected)

faculty_row = faculty_df[faculty_df["Clean"] == selected_clean]

designation = str(faculty_row.iloc[0].get("Designation", "")).strip()

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

val_dates = []
for col in ["V1", "V2", "V3", "V4", "V5"]:
    if col in faculty_df.columns:
        value = faculty_row.iloc[0][col]
        if pd.notna(value):
            val_dates.append(to_date(value))

val_set = set(val_dates)

col_left, col_right = st.columns(2)

# ---------------- WILLINGNESS ---------------- #

with col_left:
    st.markdown("<div class='section-title'>Willingness Selection</div>", unsafe_allow_html=True)
    st.write(f"Designation: {designation}")
    st.write(f"Options Required: {required_count}")

    offline_pool = allocation_df[allocation_df["Mode"] == "Offline"].copy()

    choices = []
    for _, r in offline_pool.iterrows():
        dt = to_date(r["Date"])
        if dt in val_set:
            continue
        choices.append(f"{dt.strftime('%d-%m-%Y')} | {r['Session']}")

    choices = sorted(set(choices))

    picked = st.multiselect(
        f"Pick exactly {required_count} slots",
        options=choices,
        default=st.session_state.selected_slots,
    )

    st.session_state.selected_slots = picked
    st.write(f"Selected: {len(picked)} / {required_count}")

    if st.button("Submit Willingness", disabled=len(picked) != required_count):
        new_rows = []
        for item in picked:
            date_txt, session = [x.strip() for x in item.split("|")]
            new_rows.append({"Faculty": selected, "Date": date_txt, "Session": session})

        out_df = pd.DataFrame(new_rows)

        if os.path.exists(WILLINGNESS_FILE):
            existing_df = pd.read_excel(WILLINGNESS_FILE)
            out_df = pd.concat([existing_df, out_df], ignore_index=True)

        out_df.to_excel(WILLINGNESS_FILE, index=False)
        st.success("Willingness submitted successfully.")
        st.session_state.selected_slots = []


# ---------------- CURRENT DUTIES ---------------- #

with col_right:
    st.markdown("<div class='section-title'>Assigned Duties</div>", unsafe_allow_html=True)

    inv = allocation_df[allocation_df["Faculty"] == selected_clean].copy()

    if not inv.empty:
        inv["Date"] = pd.to_datetime(inv["Date"]).dt.date
        inv["Day"] = pd.to_datetime(inv["Date"]).dt.day_name()
        st.dataframe(inv[["Date", "Day", "Session", "Mode"]], use_container_width=True, hide_index=True)
    else:
        st.info("No duties assigned")

    st.markdown("<div class='section-title'>Valuation Dates</div>", unsafe_allow_html=True)

    if val_dates:
        val_df = pd.DataFrame({"Date": val_dates})
        val_df["Day"] = pd.to_datetime(val_df["Date"]).dt.day_name()
        st.dataframe(val_df, use_container_width=True, hide_index=True)
    else:
        st.info("No valuation dates")


st.markdown("---")
st.markdown("Curated by Dr. N. Sathiya Narayanan, School of Mechanical Engineering")
