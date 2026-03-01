diff --git a/web_app.py b/web_app.py
index 701a6c8cc53188a57da2c35d09312e4d178a4ed0..f35fdda60026dfca0810b0d21b3f26187adb0a24 100644
--- a/web_app.py
+++ b/web_app.py
@@ -1,201 +1,370 @@
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
+import calendar as calmod
+import pandas as pd
+import streamlit as st
+import altair as alt
+
+# ---------------- CONFIG ---------------- #
+FACULTY_FILE = "Faculty_Master.xlsx"
+OFFLINE_FILE = "Offline_Duty.xlsx"
+ONLINE_FILE = "Online_Duty.xlsx"
+WILLINGNESS_FILE = "Willingness.xlsx"
+LOGO_FILE = "sastra_logo.png"
+
+st.set_page_config(page_title="SASTRA Duty Portal", layout="wide")
+
+
+# ---------------- FUNCTIONS ---------------- #
+def clean(x):
+    return str(x).strip().lower()
+
+
+def normalize_session(value):
+    text = str(value).strip().upper()
+    if text in {"FN", "FORENOON", "MORNING", "AM"}:
+        return "FN"
+    if text in {"AN", "AFTERNOON", "EVENING", "PM"}:
+        return "AN"
+    return text
+
+
+def load_excel(file_path):
+    if not os.path.exists(file_path):
+        st.error(f"{file_path} not found in repository.")
+        st.stop()
+    return pd.read_excel(file_path)
+
+
+def normalize_duty_df(df):
+    df = df.copy()
+    df.columns = df.columns.str.strip()
+    if len(df.columns) < 3:
+        st.error("Duty files must include Date, Session, and Required columns.")
+        st.stop()
+
+    df.rename(
+        columns={
+            df.columns[0]: "Date",
+            df.columns[1]: "Session",
+            df.columns[2]: "Required",
+        },
+        inplace=True,
+    )
+    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
+    df = df.dropna(subset=["Date"]).copy()
+    df["Session"] = df["Session"].apply(normalize_session)
+    df["Required"] = pd.to_numeric(df["Required"], errors="coerce").fillna(1).astype(int)
+    return df
+
+
+def valuation_dates_for_faculty(faculty_row):
+    dates = []
+    for col in ["V1", "V2", "V3", "V4", "V5"]:
+        if col in faculty_row.index and pd.notna(faculty_row[col]):
+            dates.append(pd.to_datetime(faculty_row[col], dayfirst=True).date())
+    return sorted(set(dates))
+
+
+def demand_category(required, min_d, max_d):
+    gap = (max_d - min_d) / 3 if max_d != min_d else 1
+    low_max = round(min_d + gap)
+    mid_max = round(min_d + 2 * gap)
+    if required <= low_max:
+        return "Low"
+    if required <= mid_max:
+        return "Medium"
+    return "High"
+
+
+def build_month_calendar_frame(duty_df, valuation_dates, year, month):
+    duty_demand = duty_df.groupby("Date", as_index=False)["Required"].sum()
+    demand_map = {d.date(): int(r) for d, r in zip(duty_demand["Date"], duty_demand["Required"])}
+
+    month_start = pd.Timestamp(year=year, month=month, day=1)
+    month_end = month_start + pd.offsets.MonthEnd(0)
+    month_days = pd.date_range(month_start, month_end, freq="D")
+
+    month_demands = [demand_map.get(dt.date(), 0) for dt in month_days]
+    min_d = min(month_demands) if month_demands else 0
+    max_d = max(month_demands) if month_demands else 1
+
+    first_weekday = month_start.weekday()  # Mon=0
+    rows = []
+    weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
+    for dt in month_days:
+        week_no = ((dt.day + first_weekday - 1) // 7) + 1
+        req = demand_map.get(dt.date(), 0)
+
+        if dt.date() in valuation_dates:
+            category = "Valuation Locked"
+        elif req == 0:
+            category = "No Duty"
+        else:
+            category = demand_category(req, min_d, max_d)
+
+        rows.append(
+            {
+                "Date": dt,
+                "Week": week_no,
+                "Weekday": weekday_labels[dt.weekday()],
+                "DayNum": dt.day,
+                "Required": req,
+                "Category": category,
+                "DateLabel": dt.strftime("%d-%m-%Y"),
+            }
+        )
+    return pd.DataFrame(rows)
+
+
+def render_month_calendars(duty_df, valuation_dates, title):
+    st.markdown(f"#### {title}")
+    months = sorted({(d.year, d.month) for d in duty_df["Date"]})
+
+    color_scale = alt.Scale(
+        domain=["No Duty", "Low", "Medium", "High", "Valuation Locked"],
+        range=["#ececec", "#2ca02c", "#ff9800", "#d62728", "#7b1fa2"],
+    )
+
+    for year, month in months:
+        frame = build_month_calendar_frame(duty_df, set(valuation_dates), year, month)
+        st.markdown(f"**{calmod.month_name[month]} {year}**")
+
+        base = alt.Chart(frame).encode(
+            x=alt.X("Weekday:N", sort=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], title=""),
+            y=alt.Y("Week:O", sort="ascending", title=""),
+            tooltip=[
+                alt.Tooltip("DateLabel:N", title="Date"),
+                alt.Tooltip("Required:Q", title="Demand"),
+                alt.Tooltip("Category:N", title="Category"),
+            ],
+        )
+
+        rect = base.mark_rect(stroke="white").encode(
+            color=alt.Color("Category:N", scale=color_scale, legend=alt.Legend(title="Heat Map"))
+        )
+        text = base.mark_text(color="black", fontSize=12).encode(text="DayNum:Q")
+        st.altair_chart((rect + text).properties(height=220), use_container_width=True)
+
+
+def load_willingness():
+    if os.path.exists(WILLINGNESS_FILE):
+        df = pd.read_excel(WILLINGNESS_FILE)
+        if "Faculty" not in df.columns:
+            df["Faculty"] = ""
+        df["FacultyClean"] = df["Faculty"].apply(clean)
+        return df
+    return pd.DataFrame(columns=["Faculty", "Date", "Session", "FacultyClean"])
+
+
+def render_branding_header(show_logo=True):
+    if show_logo and os.path.exists(LOGO_FILE):
+        st.image(LOGO_FILE, use_container_width=True)
+
+    st.markdown("## SASTRA SoME End Semester Examination Duty Portal")
+    st.markdown("### School of Mechanical Engineering")
+    st.markdown("---")
+
+
+# ---------------- LOGIN ---------------- #
+if "logged_in" not in st.session_state:
+    st.session_state.logged_in = False
+
+if not st.session_state.logged_in:
+    render_branding_header(show_logo=True)
+    st.info("Official Notice: Willingness will be accommodated as much as possible based on institutional requirements.")
+    c1, c2, c3 = st.columns([1, 2, 1])
+    with c2:
+        st.subheader("Faculty Login")
+        username = st.text_input("Username")
+        password = st.text_input("Password", type="password")
+        if st.button("Login"):
+            if username == "SASTRA" and password == "SASTRA":
+                st.session_state.logged_in = True
+                st.rerun()
+            else:
+                st.error("Invalid credentials")
+    st.markdown("---")
+    st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
+    st.stop()
+
+# ---------------- LOAD DATA ---------------- #
+faculty_df = load_excel(FACULTY_FILE)
+offline_df = normalize_duty_df(load_excel(OFFLINE_FILE))
+online_df = normalize_duty_df(load_excel(ONLINE_FILE))
+
+faculty_df.columns = faculty_df.columns.str.strip()
+if len(faculty_df.columns) < 2:
+    st.error("Faculty_Master.xlsx must include Name and Designation columns.")
+    st.stop()
+
+faculty_df.rename(columns={faculty_df.columns[0]: "Name", faculty_df.columns[1]: "Designation"}, inplace=True)
+faculty_df["Clean"] = faculty_df["Name"].apply(clean)
+
+# ---------------- HEADER ---------------- #
+render_branding_header(show_logo=False)
+st.info("Official Notice: Willingness will be accommodated as much as possible based on institutional requirements.")
+
+# ---------------- FACULTY SELECT ---------------- #
+selected_name = st.selectbox("Select Your Name", sorted(faculty_df["Name"].dropna().unique()))
+selected_clean = clean(selected_name)
+faculty_row_df = faculty_df[faculty_df["Clean"] == selected_clean]
+if faculty_row_df.empty:
+    st.error("Selected faculty not found in Faculty_Master.xlsx")
+    st.stop()
+
+faculty_row = faculty_row_df.iloc[0]
+designation = str(faculty_row["Designation"]).strip()
+designation_key = designation.upper()
+
+# ---------------- DUTY STRUCTURE ---------------- #
+duty_structure = {
+    "P": 3,
+    "ACP": 5,
+    "SAP": 7,
+    "AP3": 7,
+    "AP2": 7,
+    "TA": 9,
+    "RA": 9,
+}
+required_count = duty_structure.get(designation_key, 0)
+if required_count == 0:
+    st.warning("Designation rule not found. Please verify designation values in Faculty_Master.xlsx.")
+
+valuation_dates = valuation_dates_for_faculty(faculty_row)
+valuation_set = set(valuation_dates)
+
+offline_options = offline_df[["Date", "Session"]].drop_duplicates().sort_values(["Date", "Session"])
+offline_options["DateOnly"] = offline_options["Date"].dt.date
+valid_dates = sorted([d for d in offline_options["DateOnly"].unique() if d not in valuation_set])
+
+if "selected_faculty" not in st.session_state:
+    st.session_state.selected_faculty = selected_clean
+if "selected_slots" not in st.session_state:
+    st.session_state.selected_slots = []
+if "picked_date" not in st.session_state:
+    st.session_state.picked_date = valid_dates[0] if valid_dates else None
+
+if st.session_state.selected_faculty != selected_clean:
+    st.session_state.selected_faculty = selected_clean
+    st.session_state.selected_slots = []
+    st.session_state.picked_date = valid_dates[0] if valid_dates else None
+
+# ---------------- LAYOUT ---------------- #
+left, right = st.columns([1, 1.4])
+
+with left:
+    st.subheader("Willingness Selection")
+    st.write(f"**Designation:** {designation}")
+    st.write(f"**Options Required:** {required_count}")
+
+    # requested: do not start willingness by default, only after user adds
+    if not valid_dates:
+        st.warning("No selectable offline dates available after valuation blocking.")
+    else:
+        picked_date = st.selectbox(
+            "Choose Offline Date",
+            valid_dates,
+            key="picked_date",
+            format_func=lambda d: d.strftime("%d-%m-%Y (%A)"),
+        )
+
+        available = set(offline_options[offline_options["DateOnly"] == picked_date]["Session"].dropna().astype(str).str.upper())
+        btn1, btn2 = st.columns(2)
+        with btn1:
+            add_fn = st.button(
+                "Add FN",
+                use_container_width=True,
+                disabled=("FN" not in available) or (len(st.session_state.selected_slots) >= required_count),
+            )
+        with btn2:
+            add_an = st.button(
+                "Add AN",
+                use_container_width=True,
+                disabled=("AN" not in available) or (len(st.session_state.selected_slots) >= required_count),
+            )
+
+        def add_slot(session):
+            existing_dates = {item["Date"] for item in st.session_state.selected_slots}
+            slot = {"Date": picked_date, "Session": session}
+            if picked_date in valuation_set:
+                st.warning("Valuation date cannot be selected.")
+            elif picked_date in existing_dates:
+                st.warning("FN and AN on the same date are not allowed.")
+            elif len(st.session_state.selected_slots) >= required_count:
+                st.warning("Required count already reached.")
+            elif slot in st.session_state.selected_slots:
+                st.warning("This date-session is already selected.")
+            else:
+                st.session_state.selected_slots.append(slot)
+
+        if add_fn:
+            add_slot("FN")
+        if add_an:
+            add_slot("AN")
+
+    st.session_state.selected_slots = st.session_state.selected_slots[:required_count]
+    st.write(f"**Selected:** {len(st.session_state.selected_slots)} / {required_count}")
+
+    selected_df = pd.DataFrame(st.session_state.selected_slots)
+    if not selected_df.empty:
+        selected_df = selected_df.sort_values(["Date", "Session"]).copy().reset_index(drop=True)
+        selected_df.insert(0, "Sl.No", selected_df.index + 1)
+        selected_df["Day"] = pd.to_datetime(selected_df["Date"]).dt.day_name()
+        selected_df["Date"] = pd.to_datetime(selected_df["Date"]).dt.strftime("%d-%m-%Y")
+        st.dataframe(selected_df[["Sl.No", "Date", "Day", "Session"]], use_container_width=True, hide_index=True)
+
+        remove_sl = st.selectbox(
+            "Select Sl.No to remove",
+            options=selected_df["Sl.No"].tolist(),
+            format_func=lambda x: f"{x}",
+        )
+        if st.button("Remove Selected Row", use_container_width=True):
+            target_row = selected_df[selected_df["Sl.No"] == remove_sl].iloc[0]
+            target_date = pd.to_datetime(target_row["Date"], dayfirst=True).date()
+            target_session = target_row["Session"]
+            st.session_state.selected_slots = [
+                s for s in st.session_state.selected_slots
+                if not (s["Date"] == target_date and s["Session"] == target_session)
+            ]
+
+    willingness_df = load_willingness()
+    already_submitted = False
+    if "FacultyClean" in willingness_df.columns:
+        already_submitted = selected_clean in set(willingness_df["FacultyClean"].astype(str).tolist())
+
+    st.markdown("### Submit Willingness")
+    if already_submitted:
+        st.warning("You have already submitted willingness.")
+
+    remaining = max(required_count - len(st.session_state.selected_slots), 0)
+    if already_submitted:
+        st.info("Verification: Submission already exists for this faculty.")
+    elif remaining == 0 and required_count > 0:
+        st.success("Verification: Required willingness count completed. You can submit now.")
+    else:
+        st.info(f"Verification: Select {remaining} more option(s) to enable submission.")
+
+    submit_disabled = already_submitted or len(st.session_state.selected_slots) != required_count
+    submitted = st.button("Submit Willingness", disabled=submit_disabled, use_container_width=True)
+    if submitted:
+        new_rows = [
+            {"Faculty": selected_name, "Date": item["Date"].strftime("%d-%m-%Y"), "Session": item["Session"]}
+            for item in st.session_state.selected_slots
+        ]
+        out_df = pd.concat([willingness_df.drop(columns=["FacultyClean"], errors="ignore"), pd.DataFrame(new_rows)], ignore_index=True)
+        out_df.to_excel(WILLINGNESS_FILE, index=False)
+        st.toast("University Examination Committee thanks you for providing your willingness.", icon="✅")
+        st.success(
+            "University Examination Committee thanks you for providing your willingness. "
+            "The exact duty allocation will be determined through AI-assisted optimization "
+            "integrated with Google OR-Tools. We request your continued support."
+        )
+        st.session_state.selected_slots = []
+
+with right:
+    render_month_calendars(offline_df, valuation_set, "Offline Duty Calendar")
+    if designation in {"P", "ACP"}:
+        render_month_calendars(online_df, valuation_set, "Online Duty Calendar")
+
+st.markdown("---")
+st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
