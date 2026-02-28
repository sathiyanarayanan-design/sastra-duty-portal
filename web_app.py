import streamlit as st
import pandas as pd

# ================= CONFIG =================

FACULTY_FILE = "Faculty_Master.xlsx"
ALLOCATION_FILE = "Final_Allocation.xlsx"
LOGO_FILE = "sastra_logo.png"

def clean(x):
    return str(x).strip().lower()

st.set_page_config(
    page_title="SASTRA End Sem Duty Portal",
    layout="wide"
)

# ================= CUSTOM STYLING =================

st.markdown("""
<style>
.main-title {
    text-align:center;
    font-size:42px;
    font-weight:800;
    color:#800000;
}

.sub-title {
    text-align:center;
    font-size:26px;
    font-weight:600;
    color:#003366;
}

.section-title {
    font-size:24px;
    font-weight:700;
}

.flash-disclaimer {
    padding:15px;
    background-color:#fff3cd;
    border:2px solid #ff0000;
    font-weight:600;
    font-size:16px;
    animation: flash 1s infinite;
}

@keyframes flash {
    0% { background-color: #fff3cd; }
    50% { background-color: #ffcccc; }
    100% { background-color: #fff3cd; }
}

.curated {
    text-align:center;
    font-style:italic;
    font-size:16px;
    margin-top:10px;
}
</style>
""", unsafe_allow_html=True)

# ================= HEADER =================

def header_section():

    st.image(LOGO_FILE, use_container_width=True)

    st.markdown(
        "<div class='main-title'>"
        "SASTRA SOME End Semester Examination Duty Portal"
        "</div>",
        unsafe_allow_html=True
    )

    st.markdown(
        "<div class='sub-title'>"
        "School of Mechanical Engineering"
        "</div>",
        unsafe_allow_html=True
    )

    st.markdown("---")

# ================= LOGIN =================

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:

    header_section()

    col1, col2, col3 = st.columns([1,2,1])

    with col2:
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

# ================= LOAD DATA =================

faculty_df = pd.read_excel(FACULTY_FILE)
allocation_df = pd.read_excel(ALLOCATION_FILE)

faculty_df["Clean"] = faculty_df.iloc[:,0].apply(clean)
allocation_df["Faculty"] = allocation_df["Faculty"].apply(clean)

# ================= MAIN PAGE =================

header_section()

selected = st.selectbox(
    "Select Your Name",
    sorted(faculty_df.iloc[:,0])
)

selected_clean = clean(selected)

col1, col2 = st.columns(2)

# ================= INVIGILATION =================

with col1:
    st.markdown("<div class='section-title'>Invigilation Duties</div>", unsafe_allow_html=True)

    inv = allocation_df[allocation_df["Faculty"] == selected_clean]

    if not inv.empty:
        inv_display = inv.copy()
        inv_display["Date"] = pd.to_datetime(inv_display["Date"]).dt.date
        inv_display["Day"] = pd.to_datetime(inv_display["Date"]).dt.day_name()
        inv_display = inv_display[["Date","Day","Session","Mode"]]
        st.dataframe(inv_display, use_container_width=True, hide_index=True)
    else:
        st.info("No Invigilation Duties Assigned")

# ================= VALUATION =================

with col2:
    st.markdown("<div class='section-title'>Valuation Duties</div>", unsafe_allow_html=True)

    faculty_row = faculty_df[faculty_df["Clean"] == selected_clean]

    val_list = []

    if not faculty_row.empty:
        for col in ["V1","V2","V3","V4","V5"]:
            if col in faculty_df.columns:
                val = faculty_row.iloc[0][col]
                if pd.notna(val):
                    val_list.append(val)

    if val_list:
        val_df = pd.DataFrame({"Date": val_list})
        val_df["Date"] = pd.to_datetime(val_df["Date"]).dt.date
        val_df["Day"] = pd.to_datetime(val_df["Date"]).dt.day_name()
        val_df["Duration"] = "Full Day"
        val_df = val_df[["Date","Day","Duration"]]
        st.dataframe(val_df, use_container_width=True, hide_index=True)
    else:
        st.info("No Valuation Duties Assigned")

# ================= DISCLAIMER =================

st.markdown("---")

st.markdown(
"""
<div class='flash-disclaimer'>
DISCLAIMER: This AI-Based Faculty Duty Allocation System follows institutional policy rules and structured allocation constraints. 
Minor mismatches may occur due to data limitations.  

In case of discrepancy, contact the University Examination Committee, School of Mechanical Engineering.  

QP Feedback Dates: Kindly verify with the SASTRA University Web Portal Exam Schedule.
</div>
""",
unsafe_allow_html=True
)

st.markdown(
"""
<div class='curated'>
Curated by Dr. N. Sathiya Narayanan, School of Mechanical Engineering
</div>
""",
unsafe_allow_html=True
)