diff --git a/web_app.py b/web_app.py
index 701a6c8cc53188a57da2c35d09312e4d178a4ed0..5a4be731057ebfc3e9a07badc1103f26458fc6bd 100644
--- a/web_app.py
+++ b/web_app.py
@@ -1,201 +1,200 @@
-import streamlit as st
-import pandas as pd
-
-# ================= CONFIG =================
-
-FACULTY_FILE = "Faculty_Master.xlsx"
-ALLOCATION_FILE = "Final_Allocation.xlsx"
-LOGO_FILE = "sastra_logo.png"
-
-def clean(x):
-    return str(x).strip().lower()
-
-st.set_page_config(
-    page_title="SASTRA End Sem Duty Portal",
-    layout="wide"
-)
-
-# ================= CUSTOM STYLING =================
-
-st.markdown("""
-<style>
-.main-title {
-    text-align:center;
-    font-size:42px;
-    font-weight:800;
-    color:#800000;
-}
-
-.sub-title {
-    text-align:center;
-    font-size:26px;
-    font-weight:600;
-    color:#003366;
-}
-
-.section-title {
-    font-size:24px;
-    font-weight:700;
-}
-
-.flash-disclaimer {
-    padding:15px;
-    background-color:#fff3cd;
-    border:2px solid #ff0000;
-    font-weight:600;
-    font-size:16px;
-    animation: flash 1s infinite;
-}
-
-@keyframes flash {
-    0% { background-color: #fff3cd; }
-    50% { background-color: #ffcccc; }
-    100% { background-color: #fff3cd; }
-}
-
-.curated {
-    text-align:center;
-    font-style:italic;
-    font-size:16px;
-    margin-top:10px;
-}
-</style>
-""", unsafe_allow_html=True)
-
-# ================= HEADER =================
-
-def header_section():
-
-    st.image(LOGO_FILE, use_container_width=True)
-
-    st.markdown(
-        "<div class='main-title'>"
-        "SASTRA SOME End Semester Examination Duty Portal"
-        "</div>",
-        unsafe_allow_html=True
-    )
-
-    st.markdown(
-        "<div class='sub-title'>"
-        "School of Mechanical Engineering"
-        "</div>",
-        unsafe_allow_html=True
-    )
-
-    st.markdown("---")
-
-# ================= LOGIN =================
-
-if "logged_in" not in st.session_state:
-    st.session_state.logged_in = False
-
-if not st.session_state.logged_in:
-
-    header_section()
-
-    col1, col2, col3 = st.columns([1,2,1])
-
-    with col2:
-        st.markdown("<div class='section-title'>Faculty Login</div>", unsafe_allow_html=True)
-
-        username = st.text_input("Username")
-        password = st.text_input("Password", type="password")
-
-        if st.button("Login"):
-            if username == "SASTRA" and password == "SASTRA":
-                st.session_state.logged_in = True
-                st.rerun()
-            else:
-                st.error("Invalid Credentials")
-
-    st.stop()
-
-# ================= LOAD DATA =================
-
-faculty_df = pd.read_excel(FACULTY_FILE)
-allocation_df = pd.read_excel(ALLOCATION_FILE)
-
-faculty_df["Clean"] = faculty_df.iloc[:,0].apply(clean)
-allocation_df["Faculty"] = allocation_df["Faculty"].apply(clean)
-
-# ================= MAIN PAGE =================
-
-header_section()
-
-selected = st.selectbox(
-    "Select Your Name",
-    sorted(faculty_df.iloc[:,0])
-)
-
-selected_clean = clean(selected)
-
-col1, col2 = st.columns(2)
-
-# ================= INVIGILATION =================
-
-with col1:
-    st.markdown("<div class='section-title'>Invigilation Duties</div>", unsafe_allow_html=True)
-
-    inv = allocation_df[allocation_df["Faculty"] == selected_clean]
-
-    if not inv.empty:
-        inv_display = inv.copy()
-        inv_display["Date"] = pd.to_datetime(inv_display["Date"]).dt.date
-        inv_display["Day"] = pd.to_datetime(inv_display["Date"]).dt.day_name()
-        inv_display = inv_display[["Date","Day","Session","Mode"]]
-        st.dataframe(inv_display, use_container_width=True, hide_index=True)
-    else:
-        st.info("No Invigilation Duties Assigned")
-
-# ================= VALUATION =================
-
-with col2:
-    st.markdown("<div class='section-title'>Valuation Duties</div>", unsafe_allow_html=True)
-
-    faculty_row = faculty_df[faculty_df["Clean"] == selected_clean]
-
-    val_list = []
-
-    if not faculty_row.empty:
-        for col in ["V1","V2","V3","V4","V5"]:
-            if col in faculty_df.columns:
-                val = faculty_row.iloc[0][col]
-                if pd.notna(val):
-                    val_list.append(val)
-
-    if val_list:
-        val_df = pd.DataFrame({"Date": val_list})
-        val_df["Date"] = pd.to_datetime(val_df["Date"]).dt.date
-        val_df["Day"] = pd.to_datetime(val_df["Date"]).dt.day_name()
-        val_df["Duration"] = "Full Day"
-        val_df = val_df[["Date","Day","Duration"]]
-        st.dataframe(val_df, use_container_width=True, hide_index=True)
-    else:
-        st.info("No Valuation Duties Assigned")
-
-# ================= DISCLAIMER =================
-
-st.markdown("---")
-
-st.markdown(
-"""
-<div class='flash-disclaimer'>
-DISCLAIMER: This AI-Based Faculty Duty Allocation System follows institutional policy rules and structured allocation constraints. 
-Minor mismatches may occur due to data limitations.  
-
-In case of discrepancy, contact the University Examination Committee, School of Mechanical Engineering.  
-
-QP Feedback Dates: Kindly verify with the SASTRA University Web Portal Exam Schedule.
-</div>
-""",
-unsafe_allow_html=True
-)
-
-st.markdown(
-"""
-<div class='curated'>
-Curated by Dr. N. Sathiya Narayanan, School of Mechanical Engineering
-</div>
-""",
-unsafe_allow_html=True
-)
\ No newline at end of file
+import os
+import streamlit as st
+import pandas as pd
+
+FACULTY_FILE = "Faculty_Master.xlsx"
+ALLOCATION_FILE = "Final_Allocation.xlsx"
+WILLINGNESS_FILE = "Willingness.xlsx"
+LOGO_FILE = "sastra_logo.png"
+
+
+def clean(x):
+    return str(x).strip().lower()
+
+
+def to_date(value):
+    return pd.to_datetime(value).date()
+
+
+st.set_page_config(page_title="SASTRA End Sem Duty Portal", layout="wide")
+
+st.markdown(
+    """
+<style>
+.main-title { text-align:center; font-size:36px; font-weight:800; color:#800000; }
+.sub-title { text-align:center; font-size:22px; font-weight:600; color:#003366; }
+.section-title { font-size:22px; font-weight:700; color:#003366; margin-top:6px; }
+.simple-note { padding:10px; background-color:#fff3cd; border:1px solid #d1b35a; font-weight:600; }
+</style>
+""",
+    unsafe_allow_html=True,
+)
+
+
+def header_section():
+    st.image(LOGO_FILE, use_container_width=True)
+    st.markdown("<div class='main-title'>SASTRA SoME End Semester Examination Duty Portal</div>", unsafe_allow_html=True)
+    st.markdown("<div class='sub-title'>School of Mechanical Engineering</div>", unsafe_allow_html=True)
+    st.markdown("---")
+
+
+if "logged_in" not in st.session_state:
+    st.session_state.logged_in = False
+
+if not st.session_state.logged_in:
+    header_section()
+    c1, c2, c3 = st.columns([1, 2, 1])
+    with c2:
+        st.markdown("<div class='section-title'>Faculty Login</div>", unsafe_allow_html=True)
+        username = st.text_input("Username")
+        password = st.text_input("Password", type="password")
+        if st.button("Login"):
+            if username == "SASTRA" and password == "SASTRA":
+                st.session_state.logged_in = True
+                st.rerun()
+            st.error("Invalid Credentials")
+    st.stop()
+
+faculty_df = pd.read_excel(FACULTY_FILE)
+allocation_df = pd.read_excel(ALLOCATION_FILE)
+
+faculty_df.columns = faculty_df.columns.str.strip()
+allocation_df.columns = allocation_df.columns.str.strip()
+
+faculty_df["Clean"] = faculty_df.iloc[:, 0].apply(clean)
+allocation_df["Faculty"] = allocation_df["Faculty"].apply(clean)
+allocation_df["Date"] = pd.to_datetime(allocation_df["Date"])
+allocation_df["Session"] = allocation_df["Session"].astype(str).str.strip().str.upper()
+allocation_df["Mode"] = allocation_df["Mode"].astype(str).str.strip().str.title()
+
+if "selected_slots" not in st.session_state:
+    st.session_state.selected_slots = []
+
+header_section()
+
+st.markdown(
+    "<div class='simple-note'>Official Notice: Willingness choices will be accommodated as much as possible. Final allocation may vary based on duty requirements.</div>",
+    unsafe_allow_html=True,
+)
+
+selected = st.selectbox("Select Your Name", sorted(faculty_df.iloc[:, 0]))
+selected_clean = clean(selected)
+
+faculty_row = faculty_df[faculty_df["Clean"] == selected_clean]
+if faculty_row.empty:
+    st.error("Faculty details not found.")
+    st.stop()
+
+designation = str(faculty_row.iloc[0].get("Designation", "")).strip()
+
+duty_structure = {
+    "P": {"allotted": "1 Online", "willingness": 3},
+    "ACP": {"allotted": "1 Online + 1 Offline", "willingness": 5},
+    "SAP": {"allotted": "3 Offline", "willingness": 7},
+    "AP3": {"allotted": "3 Offline", "willingness": 7},
+    "AP2": {"allotted": "3 Offline", "willingness": 7},
+    "TA": {"allotted": "3 Offline", "willingness": 9},
+    "RA": {"allotted": "4 Offline", "willingness": 9},
+}
+rule = duty_structure.get(designation, {"allotted": "As per committee", "willingness": 0})
+required_count = int(rule["willingness"])
+
+val_dates = []
+for col in ["V1", "V2", "V3", "V4", "V5"]:
+    if col in faculty_df.columns:
+        value = faculty_row.iloc[0][col]
+        if pd.notna(value):
+            val_dates.append(to_date(value))
+val_set = set(val_dates)
+
+# reset slot selections when faculty changes
+if st.session_state.get("selected_faculty") != selected_clean:
+    st.session_state.selected_faculty = selected_clean
+    st.session_state.selected_slots = []
+
+col_left, col_right = st.columns([1.05, 1.15])
+
+with col_left:
+    st.markdown("<div class='section-title'>Profile & Willingness</div>", unsafe_allow_html=True)
+    st.write(f"**Designation:** {designation}")
+    st.write(f"**Duties to be Allotted:** {rule['allotted']}")
+    st.write(f"**Options Required:** {required_count}")
+
+    existing_submitted = False
+    if os.path.exists(WILLINGNESS_FILE):
+        existing_df = pd.read_excel(WILLINGNESS_FILE)
+        if "Faculty" in existing_df.columns:
+            existing_submitted = selected in existing_df["Faculty"].astype(str).values
+
+    offline_pool = allocation_df[allocation_df["Mode"] == "Offline"].copy()
+    if offline_pool.empty:
+        offline_pool = allocation_df.copy()
+
+    choices = []
+    for _, r in offline_pool.sort_values(["Date", "Session"]).iterrows():
+        dt = to_date(r["Date"])
+        if dt in val_set:
+            continue
+        choices.append(f"{dt.strftime('%d-%m-%Y')} | {r['Session']}")
+
+    choices = sorted(set(choices))
+
+    picked = st.multiselect(
+        f"Pick exactly {required_count} Offline slots (valuation dates are blocked)",
+        options=choices,
+        default=st.session_state.selected_slots,
+    )
+    st.session_state.selected_slots = picked
+    st.write(f"**Selected:** {len(picked)} / {required_count}")
+
+    can_submit = (not existing_submitted) and (len(picked) == required_count)
+    if existing_submitted:
+        st.warning("You have already submitted willingness.")
+
+    if st.button("Submit Willingness", disabled=not can_submit, use_container_width=True):
+        new_rows = []
+        for item in picked:
+            date_txt, session = [x.strip() for x in item.split("|")]
+            new_rows.append({"Faculty": selected, "Date": date_txt, "Session": session})
+
+        out_df = pd.DataFrame(new_rows)
+        if os.path.exists(WILLINGNESS_FILE):
+            existing_df = pd.read_excel(WILLINGNESS_FILE)
+            if "Faculty" in existing_df.columns and selected in existing_df["Faculty"].astype(str).values:
+                st.warning("Already submitted. Duplicate not saved.")
+            else:
+                out_df = pd.concat([existing_df, out_df], ignore_index=True)
+                out_df.to_excel(WILLINGNESS_FILE, index=False)
+                st.success("Willingness submitted successfully.")
+                st.session_state.selected_slots = []
+        else:
+            out_df.to_excel(WILLINGNESS_FILE, index=False)
+            st.success("Willingness submitted successfully.")
+            st.session_state.selected_slots = []
+
+    if designation in {"P", "ACP"}:
+        online_dates = sorted({to_date(x) for x in allocation_df[allocation_df["Mode"] == "Online"]["Date"]})
+        if online_dates:
+            st.info("**Online duty dates (reference for P/ACP):**\n\n" + ", ".join(d.strftime("%d-%m-%Y") for d in online_dates))
+
+with col_right:
+    st.markdown("<div class='section-title'>Current Assigned Duties</div>", unsafe_allow_html=True)
+    inv = allocation_df[allocation_df["Faculty"] == selected_clean].copy()
+    if not inv.empty:
+        inv["Date"] = pd.to_datetime(inv["Date"]).dt.date
+        inv["Day"] = pd.to_datetime(inv["Date"]).dt.day_name()
+        st.dataframe(inv[["Date", "Day", "Session", "Mode"]], use_container_width=True, hide_index=True)
+    else:
+        st.info("No duties assigned")
+
+    st.markdown("<div class='section-title'>Valuation Dates</div>", unsafe_allow_html=True)
+    if val_dates:
+        val_df = pd.DataFrame({"Date": val_dates})
+        val_df["Day"] = pd.to_datetime(val_df["Date"]).dt.day_name()
+        val_df["Status"] = "Blocked for willingness"
+        st.dataframe(val_df[["Date", "Day", "Status"]], use_container_width=True, hide_index=True)
+    else:
+        st.info("No valuation dates")
+
+st.markdown("---")
+st.markdown("Curated by Dr. N. Sathiya Narayanan, School of Mechanical Engineering")
