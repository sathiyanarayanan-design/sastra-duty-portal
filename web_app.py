+import os
+import calendar as calmod
+import pandas as pd
+import tkinter as tk
+from tkinter import ttk, messagebox
+from tkcalendar import Calendar
+from PIL import Image, ImageTk
+
+# ================= FILES =================
+FACULTY_FILE = "Faculty_Master.xlsx"
+OFFLINE_FILE = "Offline_Duty.xlsx"
+ONLINE_FILE = "Online_Duty.xlsx"
+WILLINGNESS_FILE = "Willingness.xlsx"
+LOGO_FILE = "sastra_logo.png"
+
+# ================= LOAD DATA =================
+faculty_df = pd.read_excel(FACULTY_FILE)
+offline_df = pd.read_excel(OFFLINE_FILE)
+online_df = pd.read_excel(ONLINE_FILE)
+
+faculty_df.columns = faculty_df.columns.str.strip()
+offline_df.columns = offline_df.columns.str.strip()
+online_df.columns = online_df.columns.str.strip()
+
+faculty_df.rename(columns={
+    faculty_df.columns[0]: "Name",
+    faculty_df.columns[1]: "Designation"
+}, inplace=True)
+
+offline_df.rename(columns={
+    offline_df.columns[0]: "Date",
+    offline_df.columns[1]: "Session",
+    offline_df.columns[2]: "Required"
+}, inplace=True)
+
+online_df.rename(columns={
+    online_df.columns[0]: "Date",
+    online_df.columns[1]: "Session",
+    online_df.columns[2]: "Required"
+}, inplace=True)
+
+offline_df["Date"] = pd.to_datetime(offline_df["Date"], dayfirst=True)
+online_df["Date"] = pd.to_datetime(online_df["Date"], dayfirst=True)
+offline_df["Session"] = offline_df["Session"].astype(str).str.strip().str.upper()
+online_df["Session"] = online_df["Session"].astype(str).str.strip().str.upper()
+
+all_dates = pd.concat([offline_df["Date"], online_df["Date"]])
+exam_start_date = all_dates.min()
+exam_end_date = all_dates.max()
+
+# ================= DUTY STRUCTURE =================
+duty_structure = {
+    "P": {"allotted": "1 Online", "willingness": 3},
+    "ACP": {"allotted": "1 Online + 1 Offline", "willingness": 5},
+    "SAP": {"allotted": "3 Offline", "willingness": 7},
+    "AP3": {"allotted": "3 Offline", "willingness": 7},
+    "AP2": {"allotted": "3 Offline", "willingness": 7},
+    "TA": {"allotted": "3 Offline", "willingness": 9},
+    "RA": {"allotted": "4 Offline", "willingness": 9}
+}
+
+# ================= VALUATION MAP =================
+valuation_map = {}
+for _, row in faculty_df.iterrows():
+    dates = []
+    for col in ["V1", "V2", "V3", "V4", "V5"]:
+        if col in faculty_df.columns and pd.notna(row.get(col)):
+            dates.append(pd.to_datetime(row[col], dayfirst=True))
+    valuation_map[row["Name"]] = dates
+
+
+def month_list(start_date, end_date):
+    months = []
+    current = start_date.replace(day=1)
+    while current <= end_date:
+        months.append((current.year, current.month))
+        if current.month == 12:
+            current = current.replace(year=current.year + 1, month=1)
+        else:
+            current = current.replace(month=current.month + 1)
+    return months
+
+
+def date_to_key(date_value):
+    return pd.to_datetime(date_value).date()
+
+
+def build_heatmap(parent, duty_df, val_dates, heading_text, click_handler=None):
+    section = tk.Frame(parent, bg="white")
+    section.pack(fill="x", pady=6)
+
+    tk.Label(
+        section,
+        text=heading_text,
+        font=("Helvetica", 13, "bold"),
+        bg="white",
+        fg="#003366"
+    ).pack(pady=(0, 5))
+
+    demand = {}
+    for _, row in duty_df.iterrows():
+        demand[row["Date"]] = demand.get(row["Date"], 0) + int(row["Required"])
+
+    max_d = max(demand.values()) if demand else 1
+    min_d = min(demand.values()) if demand else 0
+    gap = (max_d - min_d) / 3 if max_d != min_d else 1
+    low_max = round(min_d + gap)
+    mid_max = round(min_d + 2 * gap)
+
+    date_min = duty_df["Date"].min()
+    date_max = duty_df["Date"].max()
+
+    grid_wrap = tk.Frame(section, bg="white")
+    grid_wrap.pack()
+
+    cal_objects = []
+    for idx, (year, month) in enumerate(month_list(date_min, date_max)):
+        tk.Label(
+            grid_wrap,
+            text=f"{calmod.month_name[month]} {year}",
+            font=("Helvetica", 12, "bold"),
+            bg="white"
+        ).grid(row=0, column=idx, padx=12)
+
+        cal_widget = Calendar(
+            grid_wrap,
+            selectmode="day",
+            year=year,
+            month=month,
+            mindate=date_min,
+            maxdate=date_max,
+            showothermonthdays=False
+        )
+        cal_widget.grid(row=1, column=idx, padx=12, pady=5)
+        cal_objects.append(cal_widget)
+
+    locked_dates = {date_to_key(v) for v in val_dates}
+    for cal_widget in cal_objects:
+        for date, count in demand.items():
+            label = str(count)
+            if date_to_key(date) in locked_dates:
+                cal_widget.calevent_create(date, label, "valuation")
+            elif count <= low_max:
+                cal_widget.calevent_create(date, label, "low")
+            elif count <= mid_max:
+                cal_widget.calevent_create(date, label, "medium")
+            else:
+                cal_widget.calevent_create(date, label, "high")
+
+        cal_widget.tag_config("low", background="green")
+        cal_widget.tag_config("medium", background="orange")
+        cal_widget.tag_config("high", background="red")
+        cal_widget.tag_config("valuation", background="purple")
+
+        if click_handler:
+            cal_widget.bind("<<CalendarSelected>>", click_handler)
+
+    legend_frame = tk.Frame(section, bg="white")
+    legend_frame.pack(pady=6)
+
+    tk.Label(
+        legend_frame,
+        text="Heat Map Legend:",
+        font=("Helvetica", 11, "bold"),
+        bg="white"
+    ).grid(row=0, column=0, padx=5)
+
+    colors = [
+        ("green", "Low"),
+        ("orange", "Medium"),
+        ("red", "High"),
+        ("purple", "Valuation (Locked)")
+    ]
+
+    col_idx = 1
+    for color, text in colors:
+        tk.Label(legend_frame, text="  ", bg=color, width=2).grid(row=0, column=col_idx)
+        tk.Label(legend_frame, text=f" {text}  ", bg="white").grid(row=0, column=col_idx + 1)
+        col_idx += 2
+
+
+def faculty_portal():
+    root = tk.Tk()
+    root.title("SASTRA SoME Duty Portal")
+    root.geometry("1300x880")
+    root.configure(bg="white")
+
+    header = tk.Frame(root, bg="#800000")
+    header.pack(fill="x")
+
+    try:
+        img = Image.open(LOGO_FILE)
+        logo_height = 60
+        ratio = logo_height / img.height
+        img = img.resize((int(img.width * ratio), logo_height), Image.LANCZOS)
+        logo = ImageTk.PhotoImage(img)
+        tk.Label(header, image=logo, bg="#800000").pack(side="left", padx=15)
+        header.image = logo
+    except Exception:
+        pass
+
+    tk.Label(
+        header,
+        text="SASTRA SoME Duty Portal",
+        font=("Helvetica", 20, "bold"),
+        fg="white",
+        bg="#800000"
+    ).pack(side="left")
+
+    notice_frame = tk.Frame(root, bg="#f8f9fa")
+    notice_frame.pack(fill="x")
+    tk.Label(
+        notice_frame,
+        text=(
+            "Official Notice: The committee will try to accommodate your willingness choices as much as possible. "
+            "Final allocation may be adjusted based on overall duty requirements."
+        ),
+        bg="#f8f9fa",
+        fg="#800000",
+        font=("Helvetica", 11, "bold"),
+        wraplength=1250,
+        justify="center"
+    ).pack(pady=6)
+
+    main = tk.Frame(root, bg="white")
+    main.pack(fill="both", expand=True, padx=10, pady=5)
+
+    left = tk.Frame(main, bg="white")
+    left.pack(side="left", fill="both", expand=True, padx=10)
+
+    right = tk.Frame(main, bg="white")
+    right.pack(side="right", fill="both", expand=True, padx=10)
+
+    selected = tk.StringVar()
+    selected_slots = []
+    selected_faculty = ""
+    required_count = 0
+    val_dates = []
+    current_date = None
+
+    ttk.Label(left, text="Select Faculty", font=("Helvetica", 14, "bold")).pack(pady=5)
+    combo = ttk.Combobox(left, values=sorted(faculty_df["Name"].unique()), textvariable=selected, width=35)
+    combo.pack(pady=5)
+
+    info_label = tk.Label(left, bg="white", justify="left")
+    info_label.pack(pady=5)
+
+    online_label = tk.Label(left, bg="white", justify="left", fg="#003366", wraplength=450)
+    online_label.pack(pady=5)
+
+    counter_label = tk.Label(left, fg="#800000", bg="white", font=("Helvetica", 15, "bold"))
+    counter_label.pack(pady=5)
+
+    date_pick_label = tk.Label(left, bg="white", fg="#003366", font=("Helvetica", 12, "bold"))
+    date_pick_label.pack(pady=(10, 5))
+
+    session_btn_frame = tk.Frame(left, bg="white")
+    session_btn_frame.pack(pady=5)
+
+    fn_btn = tk.Button(session_btn_frame, text="Add FN", width=12, bg="#003366", fg="white", state="disabled")
+    an_btn = tk.Button(session_btn_frame, text="Add AN", width=12, bg="#003366", fg="white", state="disabled")
+    fn_btn.grid(row=0, column=0, padx=5)
+    an_btn.grid(row=0, column=1, padx=5)
+
+    remove_btn = tk.Button(left, text="Remove Selected Row", bg="#800000", fg="white")
+    remove_btn.pack(pady=(5, 10))
+
+    preview_tree = ttk.Treeview(right, columns=("Date", "Day", "Session"), show="headings", height=8)
+    preview_tree.heading("Date", text="Date")
+    preview_tree.heading("Day", text="Day")
+    preview_tree.heading("Session", text="Session")
+    preview_tree.pack(pady=5)
+
+    calendar_frame = tk.Frame(right, bg="white")
+    calendar_frame.pack(fill="both", expand=True)
+
+    submit_btn = tk.Button(right, text="Submit Willingness", bg="#003366", fg="white", font=("Helvetica", 14, "bold"), state="disabled")
+    submit_btn.pack(pady=10)
+
+    def available_sessions(picked_date):
+        mask = offline_df["Date"].dt.date == picked_date
+        return set(offline_df.loc[mask, "Session"].dropna().astype(str).str.upper())
+
+    def refresh_preview():
+        preview_tree.delete(*preview_tree.get_children())
+        for dt_key, session in sorted(selected_slots, key=lambda x: (x[0], x[1])):
+            preview_tree.insert("", "end", values=(dt_key.strftime("%d-%m-%Y"), dt_key.strftime("%A"), session))
+        counter_label.config(text=f"Selected {len(selected_slots)} / {required_count}")
+        if required_count > 0 and len(selected_slots) == required_count:
+            submit_btn.config(state="normal")
+        else:
+            submit_btn.config(state="disabled")
+
+    def on_calendar_select(event):
+        nonlocal current_date
+        widget = event.widget
+        picked = date_to_key(widget.selection_get())
+
+        duty_dates = set(offline_df["Date"].dt.date)
+        if picked not in duty_dates:
+            messagebox.showwarning("Invalid Date", "Please pick a valid Offline duty date.")
+            current_date = None
+            fn_btn.config(state="disabled")
+            an_btn.config(state="disabled")
+            date_pick_label.config(text="")
+            return
+
+        valuation_locked = {date_to_key(v) for v in val_dates}
+        if picked in valuation_locked:
+            messagebox.showwarning("Valuation Locked", "This date is blocked due to valuation duty.")
+            current_date = None
+            fn_btn.config(state="disabled")
+            an_btn.config(state="disabled")
+            date_pick_label.config(text="")
+            return
+
+        current_date = picked
+        date_pick_label.config(text=f"Selected Date: {picked.strftime('%d-%m-%Y (%A)')}")
+
+        sessions = available_sessions(picked)
+        fn_btn.config(state="normal" if "FN" in sessions else "disabled")
+        an_btn.config(state="normal" if "AN" in sessions else "disabled")
+
+    def add_session(session):
+        if not current_date:
+            messagebox.showwarning("No Date", "Please choose a date first from the calendar.")
+            return
+
+        if len(selected_slots) >= required_count:
+            messagebox.showwarning("Limit Reached", f"You can select only {required_count} options.")
+            return
+
+        slot = (current_date, session)
+        if slot in selected_slots:
+            messagebox.showwarning("Already Selected", "This date-session is already added.")
+            return
+
+        selected_slots.append(slot)
+        refresh_preview()
+
+    def remove_selected_row():
+        item = preview_tree.selection()
+        if not item:
+            messagebox.showwarning("No Selection", "Select a row from preview to remove.")
+            return
+
+        values = preview_tree.item(item[0], "values")
+        dt_key = pd.to_datetime(values[0], dayfirst=True).date()
+        slot = (dt_key, values[2])
+        if slot in selected_slots:
+            selected_slots.remove(slot)
+            refresh_preview()
+
+    def submit_willingness():
+        if not selected_faculty:
+            messagebox.showwarning("No Faculty", "Please select your name first.")
+            return
+
+        if len(selected_slots) != required_count:
+            messagebox.showwarning("Incomplete", f"Please select exactly {required_count} options.")
+            return
+
+        out_df = pd.DataFrame([
+            {"Faculty": selected_faculty, "Date": dt_key.strftime("%d-%m-%Y"), "Session": session}
+            for dt_key, session in selected_slots
+        ])
+
+        if os.path.exists(WILLINGNESS_FILE):
+            existing = pd.read_excel(WILLINGNESS_FILE)
+            if "Faculty" in existing.columns and selected_faculty in existing["Faculty"].astype(str).values:
+                messagebox.showwarning("Already Submitted", "Sorry, you have already submitted your willingness.")
+                return
+            out_df = pd.concat([existing, out_df], ignore_index=True)
+
+        out_df.to_excel(WILLINGNESS_FILE, index=False)
+        messagebox.showinfo("Success", "Willingness submitted successfully.")
+        root.destroy()
+
+    def show_info(event):
+        nonlocal required_count, val_dates, selected_faculty, current_date
+
+        selected_slots.clear()
+        selected_faculty = selected.get()
+        current_date = None
+        date_pick_label.config(text="")
+        fn_btn.config(state="disabled")
+        an_btn.config(state="disabled")
+        refresh_preview()
+
+        if os.path.exists(WILLINGNESS_FILE):
+            existing_df = pd.read_excel(WILLINGNESS_FILE)
+            if "Faculty" in existing_df.columns and selected_faculty in existing_df["Faculty"].astype(str).values:
+                messagebox.showwarning("Already Submitted", "Sorry, you have already submitted your willingness.")
+                return
+
+        row = faculty_df[faculty_df["Name"] == selected_faculty]
+        if row.empty:
+            return
+
+        designation = str(row.iloc[0]["Designation"]).strip()
+        rule = duty_structure.get(designation, {})
+        required_count = rule.get("willingness", 0)
+
+        info_label.config(
+            text=f"Designation: {designation}\n\n"
+                 f"Duties to be Allotted: {rule.get('allotted')}\n\n"
+                 f"Options Required: {required_count}",
+            font=("Helvetica", 14, "bold"),
+            fg="#003366"
+        )
+
+        val_dates = valuation_map.get(selected_faculty, [])
+
+        if designation in {"P", "ACP"}:
+            online_dates = sorted(online_df["Date"].dt.date.unique())
+            date_text = ", ".join(dt.strftime("%d-%m-%Y") for dt in online_dates)
+            online_label.config(
+                text="Online Duty Dates (for reference):\n" + date_text,
+                font=("Helvetica", 11, "bold")
+            )
+        else:
+            online_label.config(text="", font=("Helvetica", 11))
+
+        for widget in calendar_frame.winfo_children():
+            widget.destroy()
+
+        build_heatmap(
+            calendar_frame,
+            offline_df,
+            val_dates,
+            "Offline Duty Calendar (Select date, then choose FN/AN)",
+            click_handler=on_calendar_select
+        )
+
+    combo.bind("<<ComboboxSelected>>", show_info)
+    fn_btn.config(command=lambda: add_session("FN"))
+    an_btn.config(command=lambda: add_session("AN"))
+    remove_btn.config(command=remove_selected_row)
+    submit_btn.config(command=submit_willingness)
+
+    footer_frame = tk.Frame(root, bg="white")
+    footer_frame.pack(side="bottom", fill="x", pady=8)
+
+    tk.Label(
+        footer_frame,
+        text="Curated by Dr. N. Sathiya Narayanan",
+        bg="white",
+        fg="#800000",
+        font=("Helvetica", 12, "bold")
+    ).pack()
+
+    tk.Label(
+        footer_frame,
+        text="School of Mechanical Engineering",
+        bg="white",
+        fg="#003366",
+        font=("Helvetica", 11)
+    ).pack()
+
+    root.mainloop()
+
+
+faculty_portal()
diff --git a/web_app.py b/web_app.py
index 701a6c8cc53188a57da2c35d09312e4d178a4ed0..73db6bdbb236713c06ad37e8fbfd0cd2b9c0bf23 100644
--- a/web_app.py
+++ b/web_app.py
@@ -1,201 +1,241 @@
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
+"""Streamlit faculty duty portal."""
+
+import os
+import streamlit as st
+import pandas as pd
+
+FACULTY_BASENAME = "Faculty_Master"
+OFFLINE_BASENAME = "Offline_Duty"
+ONLINE_BASENAME = "Online_Duty"
+WILLINGNESS_BASENAME = "Willingness"
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
+def find_file(basename):
+    candidates = [
+        basename,
+        f"{basename}.xlsx",
+        f"{basename}.xls",
+        f"{basename}.csv",
+    ]
+    for file_name in candidates:
+        if os.path.exists(file_name):
+            return file_name
+    return None
+
+
+def read_df_from_path(path):
+    if path.lower().endswith(".csv"):
+        return pd.read_csv(path)
+    return pd.read_excel(path)
+
+
+def read_df_required(basename, required=True):
+    local_path = find_file(basename)
+    if local_path:
+        return read_df_from_path(local_path)
+
+    if required:
+        st.error(
+            f"Missing required file: {basename}. Expected in repository as "
+            f"{basename}.xlsx/{basename}.xls/{basename}.csv."
+        )
+        st.stop()
+    return pd.DataFrame()
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
+    if os.path.exists(LOGO_FILE):
+        st.image(LOGO_FILE, use_container_width=True)
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
+faculty_df = read_df_required(FACULTY_BASENAME, required=True)
+offline_df = read_df_required(OFFLINE_BASENAME, required=True)
+online_df = read_df_required(ONLINE_BASENAME, required=True)
+
+# Build allocation view from offline+online duty files so app uses your source files directly
+for df in (offline_df, online_df):
+    df.columns = df.columns.str.strip()
+    if len(df.columns) < 3:
+        st.error("Offline_Duty/Online_Duty must have at least Date, Session, Required columns.")
+        st.stop()
+    df.rename(columns={df.columns[0]: "Date", df.columns[1]: "Session", df.columns[2]: "Required"}, inplace=True)
+    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
+    df["Session"] = df["Session"].astype(str).str.strip().str.upper()
+
+allocation_df = pd.concat(
+    [
+        offline_df[["Date", "Session"]].assign(Mode="Offline"),
+        online_df[["Date", "Session"]].assign(Mode="Online"),
+    ],
+    ignore_index=True,
+)
+
+faculty_df.columns = faculty_df.columns.str.strip()
+if faculty_df.empty or len(faculty_df.columns) < 2:
+    st.error("Faculty_Master must include Name and Designation columns.")
+    st.stop()
+
+faculty_df.rename(columns={faculty_df.columns[0]: "Name", faculty_df.columns[1]: "Designation"}, inplace=True)
+faculty_df["Clean"] = faculty_df["Name"].apply(clean)
+allocation_df["Faculty"] = ""
+allocation_df["Date"] = pd.to_datetime(allocation_df["Date"])
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
+selected = st.selectbox("Select Your Name", sorted(faculty_df["Name"].dropna().unique()))
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
+if st.session_state.get("selected_faculty") != selected_clean:
+    st.session_state.selected_faculty = selected_clean
+    st.session_state.selected_slots = []
+
+willingness_df = pd.DataFrame(columns=["Faculty", "Date", "Session"])
+local_w = find_file(WILLINGNESS_BASENAME)
+if local_w:
+    willingness_df = read_df_from_path(local_w)
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
+    if not willingness_df.empty and "Faculty" in willingness_df.columns:
+        existing_submitted = selected in willingness_df["Faculty"].astype(str).values
+
+    choices = []
+    for _, r in offline_df.sort_values(["Date", "Session"]).iterrows():
+        dt = to_date(r["Date"])
+        if dt in val_set:
+            continue
+        choices.append(f"{dt.strftime('%d-%m-%Y')} | {r['Session']}")
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
+        out_df = pd.concat([willingness_df, pd.DataFrame(new_rows)], ignore_index=True)
+        out_df.to_excel(f"{WILLINGNESS_BASENAME}.xlsx", index=False)
+        st.success("Willingness submitted successfully to Willingness.xlsx")
+        st.session_state.selected_slots = []
+
+    if designation in {"P", "ACP"}:
+        online_dates = sorted({to_date(x) for x in online_df["Date"] if pd.notna(x)})
+        if online_dates:
+            st.info("**Online duty dates (reference for P/ACP):**\n\n" + ", ".join(d.strftime("%d-%m-%Y") for d in online_dates))
+
+with col_right:
+    st.markdown("<div class='section-title'>Duty Date Pool</div>", unsafe_allow_html=True)
+    duty_view = allocation_df.copy()
+    duty_view["Date"] = pd.to_datetime(duty_view["Date"]).dt.date
+    duty_view["Day"] = pd.to_datetime(duty_view["Date"]).dt.day_name()
+    st.dataframe(duty_view[["Date", "Day", "Session", "Mode"]], use_container_width=True, hide_index=True)
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
