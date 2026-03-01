import streamlit as st
import pandas as pd
import os

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


def load_excel(file):
    if not os.path.exists(file):
        st.error(f"{file} not found in repository.")
        st.stop()
    return pd.read_excel(file)


# ---------------- LOAD DATA ---------------- #

faculty_df = load_excel(FACULTY_FILE)
offline_df = load_excel(OFFLINE_FILE)
online_df = load_excel(ONLINE_FILE)

faculty_df.columns = faculty_df.columns.str.strip()
offline_df.columns = offline_df.columns.str.strip()
online_df.columns = online_df.columns.str.strip()

faculty_df.rename(columns={
    faculty_df.columns[0]: "Name",
    faculty_df.columns[1]: "Designation"
}, inplace=True)

faculty_df["Clean"] = faculty_df["Name"].apply(clean)

offline_df.rename(columns={
    offline_df.columns[0]: "Date",
    offline_df.columns[1]: "Session"
}, inplace=True)

online_df.rename(columns={
    online_df.columns[0]: "Date",
    online_df.columns[1]: "Session"
}, inplace=True)

offline_df["Date"] = pd.to_datetime(offline_df["Date"], dayfirst=True)
online_df["Date"] = pd.to_datetime(online_df["Date"], dayfirst=True)


# ---------------- HEADER ---------------- #

if os.path.exists(LOGO_FILE):
    st.image(LOGO_FILE, use_container_width=True)

st.markdown("## SASTRA SoME End Semester Examination Duty Portal")
st.markdown("### School of Mechanical Engineering")
st.markdown("---")

st.info("Official Notice: Willingness will be accommodated as much as possible based on institutional requirements.")


# ---------------- FACULTY SELECT ---------------- #

selected_name = st.selectbox(
    "Select Your Name",
    sorted(faculty_df["Name"].dropna().unique())
)

selected_clean = clean(selected_name)
faculty_row = faculty_df[faculty_df["Clean"] == selected_clean]

designation = faculty_row.iloc[0]["Designation"]


# ---------------- DUTY STRUCTURE ---------------- #

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


# ---------------- LAYOUT ---------------- #

col1, col2 = st.columns(2)

# -------- LEFT: WILLINGNESS -------- #

with col1:
    st.subheader("Willingness Selection")
    st.write("Designation:", designation)
    st.write("Options Required:", required_count)

    choices = []
    for _, row in offline_df.iterrows():
        dt = row["Date"].date()
        choices.append(f"{dt.strftime('%d-%m-%Y')} | {row['Session']}")

    choices = sorted(set(choices))

    selected_slots = st.multiselect(
        f"Select exactly {required_count} slots",
        choices
    )

    st.write(f"Selected: {len(selected_slots)} / {required_count}")

    if st.button("Submit Willingness", disabled=len(selected_slots) != required_count):

        rows = []
        for item in selected_slots:
            date_txt, session = item.split("|")
            rows.append({
                "Faculty": selected_name,
                "Date": date_txt.strip(),
                "Session": session.strip()
            })

        out_df = pd.DataFrame(rows)

        if os.path.exists(WILLINGNESS_FILE):
            existing = pd.read_excel(WILLINGNESS_FILE)
            out_df = pd.concat([existing, out_df], ignore_index=True)

        out_df.to_excel(WILLINGNESS_FILE, index=False)

        st.success("Willingness submitted successfully!")


# -------- RIGHT: DUTY VIEW -------- #

with col2:
    st.subheader("Offline Duty Dates")

    offline_view = offline_df.copy()
    offline_view["Date"] = offline_view["Date"].dt.date
    offline_view["Day"] = pd.to_datetime(offline_view["Date"]).dt.day_name()

    st.dataframe(
        offline_view[["Date", "Day", "Session"]],
        use_container_width=True,
        hide_index=True
    )

    st.subheader("Online Duty Dates")

    online_view = online_df.copy()
    online_view["Date"] = online_view["Date"].dt.date
    online_view["Day"] = pd.to_datetime(online_view["Date"]).dt.day_name()

    st.dataframe(
        online_view[["Date", "Day", "Session"]],
        use_container_width=True,
        hide_index=True
    )


st.markdown("---")
st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
