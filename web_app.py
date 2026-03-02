import os
import calendar as calmod
import urllib.parse
import urllib.request
import smtplib
from email.message import EmailMessage
import pandas as pd
import streamlit as st
import altair as alt

# ---------------- CONFIG ---------------- #
FACULTY_FILE = "Faculty_Master.xlsx"
OFFLINE_FILE = "Offline_Duty.xlsx"
ONLINE_FILE = "Online_Duty.xlsx"
WILLINGNESS_FILE = "Willingness.xlsx"
FINAL_ALLOTMENT_FILE = "Final_Allocation.xlsx"
LOGO_FILE = "sastra_logo.png"

st.set_page_config(page_title="SASTRA Duty Portal", layout="wide")

st.markdown(
    """
    <style>
    .stApp {
        background: #f4f7fb;
    }
    .main .block-container {
        max-width: 1180px;
        padding-top: 1.2rem;
        padding-bottom: 1.2rem;
    }
    .secure-card {
        background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
        border: 1px solid #dbe3ef;
        border-radius: 14px;
        padding: 16px 18px;
        box-shadow: 0 10px 24px rgba(15, 23, 42, 0.08);
        margin-bottom: 12px;
    }
    .panel-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 14px 16px;
        box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
        margin-bottom: 10px;
    }
    .secure-title {
        font-size: 1.08rem;
        font-weight: 700;
        color: #0f172a;
        margin-bottom: 0.2rem;
    }
    .secure-sub {
        font-size: 0.93rem;
        color: #334155;
        margin-bottom: 0;
    }
    .section-title {
        font-size: 1rem;
        font-weight: 700;
        color: #0b3a67;
        margin-bottom: 0.35rem;
    }
    .stButton>button {
        border-radius: 10px;
        border: 1px solid #cbd5e1;
        font-weight: 600;
    }
    .stDownloadButton>button {
        border-radius: 10px;
        font-weight: 600;
    }
    [data-testid="stRadio"] label p {
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)



# ---------------- FUNCTIONS ---------------- #
def clean(x):
    return str(x).strip().lower()


def normalize_session(value):
    text = str(value).strip().upper()
    if text in {"FN", "FORENOON", "MORNING", "AM"}:
        return "FN"
    if text in {"AN", "AFTERNOON", "EVENING", "PM"}:
        return "AN"
    return text


def load_excel(file_path):
    if not os.path.exists(file_path):
        st.error(f"{file_path} not found in repository.")
        st.stop()
    return pd.read_excel(file_path)


def normalize_duty_df(df):
    df = df.copy()
    df.columns = df.columns.str.strip()
    if len(df.columns) < 3:
        st.error("Duty files must include Date, Session, and Required columns.")
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
    df = df.dropna(subset=["Date"]).copy()
    df["Session"] = df["Session"].apply(normalize_session)
    df["Required"] = pd.to_numeric(df["Required"], errors="coerce").fillna(1).astype(int)
    return df


def valuation_dates_for_faculty(faculty_row):
    dates = []
    for col in ["V1", "V2", "V3", "V4", "V5"]:
        if col in faculty_row.index and pd.notna(faculty_row[col]):
            dates.append(pd.to_datetime(faculty_row[col], dayfirst=True).date())
    return sorted(set(dates))


def demand_category(required):
    if required < 3:
        return "Low (<3)"
    if 3 <= required <= 7:
        return "Medium (3-7)"
    return "High (>7)"


def build_month_calendar_frame(duty_df, valuation_dates, year, month):
    session_demand = duty_df.groupby(["Date", "Session"], as_index=False)["Required"].sum()
    demand_map = {
        (d.date(), str(sess).upper()): int(req)
        for d, sess, req in zip(session_demand["Date"], session_demand["Session"], session_demand["Required"])
    }

    month_start = pd.Timestamp(year=year, month=month, day=1)
    month_end = month_start + pd.offsets.MonthEnd(0)
    month_days = pd.date_range(month_start, month_end, freq="D")
    first_weekday = month_start.weekday()  # Mon=0
    weekday_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    rows = []
    for dt in month_days:
        week_no = ((dt.day + first_weekday - 1) // 7) + 1
        date_only = dt.date()
        for session in ["FN", "AN"]:
            req = demand_map.get((date_only, session), 0)
            if date_only in valuation_dates:
                category = "Valuation Locked"
            elif req == 0:
                category = "No Duty"
            else:
                category = demand_category(req)

            rows.append(
                {
                    "Date": dt,
                    "Week": week_no,
                    "Weekday": weekday_labels[dt.weekday()],
                    "DayNum": dt.day,
                    "Session": session,
                    "Required": req,
                    "Category": category,
                    "DateLabel": dt.strftime("%d-%m-%Y"),
                }
            )
    return pd.DataFrame(rows)


def render_month_calendars(duty_df, valuation_dates, title):
    st.markdown(f"#### {title}")
    months = sorted({(d.year, d.month) for d in duty_df["Date"]})

    color_scale = alt.Scale(
        domain=["No Duty", "Low (<3)", "Medium (3-7)", "High (>7)", "Valuation Locked"],
        range=["#ececec", "#2ca02c", "#f1c40f", "#d62728", "#ff69b4"],
    )

    st.markdown(
        "**Heat Map Legend:** "
        "⬜ No Duty  "
        "🟩 Low (<3)  "
        "🟨 Medium (3-7)  "
        "🟥 High (>7)  "
        "🩷 Valuation Locked"
    )

    for year, month in months:
        frame = build_month_calendar_frame(duty_df, set(valuation_dates), year, month)
        high_count = int((frame["Category"] == "High (>7)").sum())
        st.markdown(f"**{calmod.month_name[month]} {year}**")
        st.caption(f"High-demand session slots (>7): {high_count}")

        base = alt.Chart(frame).encode(
            x=alt.X("Weekday:N", sort=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], title=""),
            xOffset=alt.XOffset("Session:N", sort=["FN", "AN"], title=""),
            y=alt.Y("Week:O", sort="ascending", title=""),
            tooltip=[
                alt.Tooltip("DateLabel:N", title="Date"),
                alt.Tooltip("Session:N", title="Session"),
                alt.Tooltip("Required:Q", title="Demand"),
                alt.Tooltip("Category:N", title="Category"),
            ],
        )

        rect = base.mark_rect(stroke="white").encode(
            color=alt.Color("Category:N", scale=color_scale, legend=alt.Legend(title="Heat Map Legend"))
        )

        day_text = (
            alt.Chart(frame[frame["Session"] == "FN"])
            .mark_text(color="black", fontSize=11, dy=-6)
            .encode(
                x=alt.X("Weekday:N", sort=["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]),
                y=alt.Y("Week:O", sort="ascending"),
                text=alt.Text("DayNum:Q"),
            )
        )

        st.altair_chart((rect + day_text).properties(height=230), use_container_width=True)
        st.caption("Each date is split into two halves: left = FN, right = AN.")


def load_willingness():
    if os.path.exists(WILLINGNESS_FILE):
        df = pd.read_excel(WILLINGNESS_FILE)
        if "Faculty" not in df.columns:
            df["Faculty"] = ""
        df["FacultyClean"] = df["Faculty"].apply(clean)
        return df
    return pd.DataFrame(columns=["Faculty", "Date", "Session", "FacultyClean"])


def load_final_allotment():
    if os.path.exists(FINAL_ALLOTMENT_FILE):
        try:
            return pd.read_excel(FINAL_ALLOTMENT_FILE)
        except Exception:
            return pd.DataFrame()
    return pd.DataFrame()


def faculty_match_mask(df, selected_clean):
    if df.empty:
        return pd.Series([], dtype=bool)
    name_cols = [c for c in df.columns if "name" in str(c).strip().lower() or "faculty" in str(c).strip().lower()]
    if not name_cols:
        return pd.Series([False] * len(df), index=df.index)
    mask = pd.Series([False] * len(df), index=df.index)
    for col in name_cols:
        mask = mask | (df[col].astype(str).apply(clean) == selected_clean)
    return mask


def collect_qp_feedback_dates(faculty_row):
    qp_dates = []
    for col in faculty_row.index:
        col_text = str(col).strip().upper()
        if "QP" in col_text and "DATE" in col_text:
            val = faculty_row[col]
            if pd.notna(val):
                dt = pd.to_datetime(val, dayfirst=True, errors="coerce")
                if pd.notna(dt):
                    qp_dates.append(dt.strftime("%d-%m-%Y"))
    return sorted(set(qp_dates))


def format_with_day(date_text):
    dt = pd.to_datetime(date_text, dayfirst=True, errors="coerce")
    if pd.isna(dt):
        return str(date_text).strip()
    return f"{dt.strftime('%d-%m-%Y')} ({dt.strftime('%A')})"


def build_delivery_message(name, willingness_list, valuation_list, invigilation_list, qp_list, accommodated_pct):
    lines = [
        f"Allotment Summary for {name}",
        "",
        "1) Willingness Options Given:",
        *(willingness_list or ["Not available"]),
        "",
        "2) Valuation Dates (Full Day):",
        *(valuation_list or ["Not available"]),
        "",
        "3) Invigilation Dates (Final Allotment):",
        *(invigilation_list or ["Not available"]),
        "",
        "4) QP Feedback Dates:",
        *(qp_list or ["Not available"]),
        "",
        f"Willingness Accommodated: {accommodated_pct}",
    ]
    return "\n".join(lines)


def send_email_summary(to_email, subject, body):
    mailto_link = f"mailto:{urllib.parse.quote(to_email)}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    smtp_from = os.getenv("SMTP_FROM", smtp_user or "")

    if not smtp_host or not smtp_user or not smtp_pass or not smtp_from:
        return False, "Email service is not configured on server. Use the generated mail app link below.", mailto_link

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = to_email
    msg.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        return True, "Email sent successfully.", ""
    except Exception as exc:
        return False, f"Email sending failed: {exc}", mailto_link


def send_sms_summary(to_phone, body):
    sms_link = f"sms:{urllib.parse.quote(to_phone)}?body={urllib.parse.quote(body)}"
    whatsapp_link = f"https://wa.me/{urllib.parse.quote(str(to_phone).replace('+', '').replace(' ', ''))}?text={urllib.parse.quote(body)}"
    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_no = os.getenv("TWILIO_FROM_NUMBER")

    if not sid or not token or not from_no:
        return False, "SMS service is not configured on server. Use the generated SMS/WhatsApp links below.", sms_link, whatsapp_link

    payload = urllib.parse.urlencode({"To": to_phone, "From": from_no, "Body": body}).encode()
    req = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
        data=payload,
        method="POST",
    )
    auth = (f"{sid}:{token}").encode()
    req.add_header("Authorization", "Basic " + __import__("base64").b64encode(auth).decode())
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=20):
            pass
        return True, "SMS sent successfully.", "", ""
    except Exception as exc:
        return False, f"SMS sending failed: {exc}", sms_link, whatsapp_link


def render_branding_header(show_logo=True):
    if show_logo and os.path.exists(LOGO_FILE):
        c1, c2, c3 = st.columns([2, 1, 2])
        with c2:
            st.image(LOGO_FILE, width=180)

    st.markdown(
        "<h2 style='text-align:center; margin-bottom:0.25rem;'>"
        "SASTRA SoME End Semester Examination Duty Portal"
        "</h2>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<h4 style='text-align:center; margin-top:0;'>"
        "School of Mechanical Engineering"
        "</h4>",
        unsafe_allow_html=True,
    )
    st.markdown("---")


# ---------------- LOGIN ---------------- #
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    render_branding_header(show_logo=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown(
            """
            <div class="secure-card">
                <div class="secure-title">🔒 Faculty Login</div>
                <p class="secure-sub">Enter your authorized credentials to access the duty portal.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        if st.button("Sign In", use_container_width=True):
            if username == "SASTRA" and password == "SASTRA":
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error("Invalid credentials")
    st.markdown("---")
    st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()

if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False


# ---------------- LOAD DATA ---------------- #
faculty_df = load_excel(FACULTY_FILE)
offline_df = normalize_duty_df(load_excel(OFFLINE_FILE))
online_df = normalize_duty_df(load_excel(ONLINE_FILE))

faculty_df.columns = faculty_df.columns.str.strip()
if len(faculty_df.columns) < 2:
    st.error("Faculty_Master.xlsx must include Name and Designation columns.")
    st.stop()

faculty_df.rename(columns={faculty_df.columns[0]: "Name", faculty_df.columns[1]: "Designation"}, inplace=True)
faculty_df["Clean"] = faculty_df["Name"].apply(clean)

# ---------------- HEADER ---------------- #
render_branding_header(show_logo=False)

st.markdown(
    """
    <style>
    .blink-notice {
        font-weight: 700;
        color: #800000;
        padding: 10px 12px;
        border: 2px solid #800000;
        background: #fffaf5;
        border-radius: 6px;
        animation: blinkPulse 2.4s ease-in-out infinite;
    }
    @keyframes blinkPulse {
        0% { opacity: 1; }
        50% { opacity: 0.35; }
        100% { opacity: 1; }
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.markdown(
    "<div class='blink-notice'><strong>Note:</strong> The University Examination Committee sincerely appreciates your cooperation. Every effort will be made to accommodate your willingness, while ensuring adherence to institutional requirements and examination needs. The final duty allocation will be carried out using AI-assisted optimization integrated with Google OR-Tools.</div>",
    unsafe_allow_html=True,
)

if "admin_authenticated" not in st.session_state:
    st.session_state.admin_authenticated = False
if "panel_mode" not in st.session_state:
    st.session_state.panel_mode = "Admin View"
if "confirm_delete_willingness" not in st.session_state:
    st.session_state.confirm_delete_willingness = False
if "selected_slots" not in st.session_state:
    st.session_state.selected_slots = []
if "selected_faculty" not in st.session_state:
    st.session_state.selected_faculty = ""
if "acp_notice_shown_for" not in st.session_state:
    st.session_state.acp_notice_shown_for = ""
if "user_panel_mode" not in st.session_state:
    st.session_state.user_panel_mode = "Willingness"

# Control panel at top as requested
st.markdown('<div class="panel-card"><div class="section-title">Control Panel</div><p class="secure-sub">Menu: choose Admin View or User View. Under User View, choose Willingness or Allotment.</p></div>', unsafe_allow_html=True)
panel_mode = st.radio(
    "Main Menu",
    ["Admin View", "User View"],
    horizontal=True,
    key="panel_mode",
)

if panel_mode == "Admin View":
    st.markdown(
        """
        <div class="secure-card">
            <div class="secure-title">🔒 Admin View (Secure Access)</div>
            <p class="secure-sub">Administrative functions are protected. Please authenticate to continue.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if not st.session_state.admin_authenticated:
        admin_pass = st.text_input("Admin Password", type="password", key="admin_password")
        if st.button("Unlock Admin View", key="unlock_admin", use_container_width=True):
            if admin_pass == "sathya":
                st.session_state.admin_authenticated = True
                st.success("Admin access granted.")
                st.rerun()
            else:
                st.error("Invalid admin password.")
    else:
        st.success("Admin view unlocked")
        willingness_admin = load_willingness().drop(columns=["FacultyClean"], errors="ignore")
        if willingness_admin.empty:
            st.info("No willingness submissions yet.")
        else:
            view_df = willingness_admin.copy().reset_index(drop=True)
            view_df.insert(0, "Sl.No", view_df.index + 1)
            st.dataframe(view_df, use_container_width=True, hide_index=True)
            csv_data = view_df.to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download Willingness CSV",
                data=csv_data,
                file_name="Willingness_Admin_View.csv",
                mime="text/csv",
                key="download_willingness_csv",
            )

        st.markdown("#### Delete Filled Willingness")
        st.checkbox(
            "I confirm deletion of all submitted willingness records",
            key="confirm_delete_willingness",
        )
        if st.button("Delete All Willingness", key="delete_all_willingness", type="primary"):
            if st.session_state.confirm_delete_willingness:
                empty_df = pd.DataFrame(columns=["Faculty", "Date", "Session"])
                empty_df.to_excel(WILLINGNESS_FILE, index=False)
                st.success("All willingness records deleted.")
                st.session_state.confirm_delete_willingness = False
                st.rerun()
            else:
                st.error("Please confirm deletion before proceeding.")

        if st.button("Lock Admin View", key="lock_admin", use_container_width=True):
            st.session_state.admin_authenticated = False
            st.success("Admin view locked.")
            st.rerun()

    st.markdown("---")
    st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()

st.markdown('<div class="panel-card"><div class="section-title">User View Menu</div><p class="secure-sub">Choose the required user function.</p></div>', unsafe_allow_html=True)
user_panel_mode = st.radio(
    "User View Menu",
    ["Willingness", "Allotment"],
    horizontal=True,
    key="user_panel_mode",
)

if user_panel_mode == "Allotment":
    st.markdown("### Allotment Details")
    faculty_names = faculty_df["Name"].dropna().drop_duplicates().tolist()
    selected_name_allot = st.selectbox("Select Faculty", faculty_names, key="allotment_faculty")
    selected_clean_allot = clean(selected_name_allot)

    faculty_row_df_allot = faculty_df[faculty_df["Clean"] == selected_clean_allot]
    valuation_display = []
    qp_feedback_display = []
    if not faculty_row_df_allot.empty:
        faculty_row_allot = faculty_row_df_allot.iloc[0]
        valuation_display = [f"{format_with_day(d.strftime('%d-%m-%Y'))} - Full Day" for d in valuation_dates_for_faculty(faculty_row_allot)]
        qp_feedback_display = [format_with_day(d) for d in collect_qp_feedback_dates(faculty_row_allot)]

    willingness_df_allot = load_willingness()
    willingness_display = []
    willingness_pairs = set()
    if not willingness_df_allot.empty:
        willingness_mask = faculty_match_mask(willingness_df_allot, selected_clean_allot)
        willingness_rows = willingness_df_allot[willingness_mask].copy()
        if not willingness_rows.empty and {"Date", "Session"}.issubset(willingness_rows.columns):
            for d, sess in zip(willingness_rows["Date"], willingness_rows["Session"]):
                date_fmt = format_with_day(d)
                sess_fmt = str(sess).strip().upper()
                willingness_display.append(f"{date_fmt} - {sess_fmt}")
                norm_date = pd.to_datetime(d, dayfirst=True, errors="coerce")
                if pd.notna(norm_date):
                    willingness_pairs.add((norm_date.date(), sess_fmt))

    allotment_df = load_final_allotment()
    invigilation_display = []
    invigilation_pairs = set()
    if not allotment_df.empty:
        allot_mask = faculty_match_mask(allotment_df, selected_clean_allot)
        allot_rows = allotment_df[allot_mask].copy()
        if not allot_rows.empty:
            if {"Date", "Session"}.issubset(allot_rows.columns):
                for d, sess in zip(allot_rows["Date"], allot_rows["Session"]):
                    date_fmt = format_with_day(d)
                    sess_fmt = str(sess).strip().upper()
                    invigilation_display.append(f"{date_fmt} - {sess_fmt}")
                    norm_date = pd.to_datetime(d, dayfirst=True, errors="coerce")
                    if pd.notna(norm_date):
                        invigilation_pairs.add((norm_date.date(), sess_fmt))
            else:
                invigilation_display = ["Final allotment record available (date/session columns not found)."]

    accommodated_pct = "Not available"
    if willingness_pairs:
        matched = len(willingness_pairs.intersection(invigilation_pairs))
        accommodated_pct = f"{(matched / len(willingness_pairs)) * 100:.2f}% ({matched}/{len(willingness_pairs)})"

    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="panel-card"><div class="section-title">1) Willingness Options Given</div></div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": willingness_display or ["Not available"]}), use_container_width=True, hide_index=True)

        st.markdown('<div class="panel-card"><div class="section-title">3) Invigilation Dates (Final Allotment)</div></div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": invigilation_display or ["Not available"]}), use_container_width=True, hide_index=True)

    with c2:
        st.markdown('<div class="panel-card"><div class="section-title">2) Valuation Dates (Full Day)</div></div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": valuation_display or ["Not available"]}), use_container_width=True, hide_index=True)

        st.markdown('<div class="panel-card"><div class="section-title">4) QP Feedback Dates</div></div>', unsafe_allow_html=True)
        st.dataframe(pd.DataFrame({"Details": qp_feedback_display or ["Not available"]}), use_container_width=True, hide_index=True)

    st.markdown('<div class="panel-card"><div class="section-title">Willingness Accommodation</div></div>', unsafe_allow_html=True)
    st.info(f"% of willingness accommodated with final allotment: {accommodated_pct}")

    message_text = build_delivery_message(
        selected_name_allot,
        willingness_display,
        valuation_display,
        invigilation_display,
        qp_feedback_display,
        accommodated_pct,
    )

    st.markdown('<div class="panel-card"><div class="section-title">Send Full Details</div><p class="secure-sub">Provide email or phone number to receive this allotment summary.</p></div>', unsafe_allow_html=True)
    d1, d2 = st.columns(2)
    with d1:
        to_email = st.text_input("Recipient Email ID", key="allotment_email")
        if st.button("Send to Email", key="send_allotment_email", use_container_width=True):
            if not to_email.strip():
                st.warning("Please enter an email ID.")
            else:
                ok, msg, mailto_link = send_email_summary(to_email.strip(), f"Allotment Details - {selected_name_allot}", message_text)
                if ok:
                    st.success(msg)
                else:
                    st.warning(msg)
                    st.markdown(f"[Open Email App]({mailto_link})")
                    st.code(message_text, language="text")

    with d2:
        to_phone = st.text_input("Recipient Phone Number", key="allotment_phone", placeholder="e.g., +9198XXXXXXXX")
        if st.button("Send to Phone", key="send_allotment_phone", use_container_width=True):
            if not to_phone.strip():
                st.warning("Please enter a phone number.")
            else:
                ok, msg, sms_link, whatsapp_link = send_sms_summary(to_phone.strip(), message_text)
                if ok:
                    st.success(msg)
                else:
                    st.warning(msg)
                    st.markdown(f"[Open SMS App]({sms_link})")
                    st.markdown(f"[Open WhatsApp]({whatsapp_link})")
                    st.code(message_text, language="text")

    st.markdown("---")
    st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
    st.stop()

# ---------------- FACULTY SELECT ---------------- #
faculty_names = faculty_df["Name"].dropna().drop_duplicates().tolist()
selected_name = st.selectbox("Select Your Name", faculty_names)
selected_clean = clean(selected_name)
faculty_row_df = faculty_df[faculty_df["Clean"] == selected_clean]
if faculty_row_df.empty:
    st.error("Selected faculty not found in Faculty_Master.xlsx")
    st.stop()

faculty_row = faculty_row_df.iloc[0]
designation = str(faculty_row["Designation"]).strip()
designation_key = designation.upper()

duty_structure = {
    "P": 3,
    "ACP": 5,
    "SAP": 7,
    "AP3": 7,
    "AP2": 7,
    "TA": 9,
    "RA": 9,
}
required_count = duty_structure.get(designation_key, 0)
if required_count == 0:
    st.warning("Designation rule not found. Please verify designation values in Faculty_Master.xlsx.")

valuation_dates = valuation_dates_for_faculty(faculty_row)
valuation_set = set(valuation_dates)

offline_options = offline_df[["Date", "Session"]].drop_duplicates().sort_values(["Date", "Session"])
offline_options["DateOnly"] = offline_options["Date"].dt.date
online_options = online_df[["Date", "Session"]].drop_duplicates().sort_values(["Date", "Session"])
online_options["DateOnly"] = online_options["Date"].dt.date

if designation_key == "P":
    selection_options = online_options
    selection_label = "Choose Online Date"
elif designation_key == "ACP":
    selection_options = offline_options
    selection_label = "Choose Offline Date"
else:
    selection_options = offline_options
    selection_label = "Choose Offline Date"

valid_dates = sorted([d for d in selection_options["DateOnly"].unique() if d not in valuation_set])

if st.session_state.selected_faculty != selected_clean:
    st.session_state.selected_faculty = selected_clean
    st.session_state.selected_slots = []
    st.session_state.picked_date = valid_dates[0] if valid_dates else None
if "picked_date" not in st.session_state:
    st.session_state.picked_date = valid_dates[0] if valid_dates else None

left, right = st.columns([1, 1.4])

with left:
    st.subheader("Willingness Selection")
    st.write(f"**Designation:** {designation}")
    st.write(f"**Options Required:** {required_count}")

    if designation_key == "ACP":
        acp_message = (
            "Dear Sir, ACP faculty members will be given with one online and one offline duty. "
            "We request to give all your willingness for offline date based calendar. "
            "We will fix it for online and offline accordingly."
        )
        st.info(acp_message)
        if st.session_state.acp_notice_shown_for != selected_clean:
            st.session_state.acp_notice_shown_for = selected_clean
            st.toast(acp_message, icon="ℹ️")

    if not valid_dates:
        st.warning(f"No selectable {selection_label.replace('Choose ', '').lower()} available after valuation blocking.")
    else:
        picked_date = st.selectbox(
            selection_label,
            valid_dates,
            key="picked_date",
            format_func=lambda d: d.strftime("%d-%m-%Y (%A)"),
        )

        available = set(selection_options[selection_options["DateOnly"] == picked_date]["Session"].dropna().astype(str).str.upper())
        btn1, btn2 = st.columns(2)
        with btn1:
            add_fn = st.button("Add FN", use_container_width=True, disabled=("FN" not in available) or (len(st.session_state.selected_slots) >= required_count))
        with btn2:
            add_an = st.button("Add AN", use_container_width=True, disabled=("AN" not in available) or (len(st.session_state.selected_slots) >= required_count))

        def add_slot(session):
            existing_dates = {item["Date"] for item in st.session_state.selected_slots}
            slot = {"Date": picked_date, "Session": session}
            if picked_date in valuation_set:
                st.warning("Valuation date cannot be selected.")
            elif picked_date in existing_dates:
                st.warning("FN and AN on the same date are not allowed.")
            elif len(st.session_state.selected_slots) >= required_count:
                st.warning("Required count already reached.")
            elif slot in st.session_state.selected_slots:
                st.warning("This date-session is already selected.")
            else:
                st.session_state.selected_slots.append(slot)

        if add_fn:
            add_slot("FN")
        if add_an:
            add_slot("AN")

    st.session_state.selected_slots = st.session_state.selected_slots[:required_count]
    st.write(f"**Selected:** {len(st.session_state.selected_slots)} / {required_count}")

    selected_df = pd.DataFrame(st.session_state.selected_slots)
    if not selected_df.empty:
        selected_df = selected_df.sort_values(["Date", "Session"]).copy().reset_index(drop=True)
        selected_df.insert(0, "Sl.No", selected_df.index + 1)
        selected_df["Day"] = pd.to_datetime(selected_df["Date"]).dt.day_name()
        selected_df["Date"] = pd.to_datetime(selected_df["Date"]).dt.strftime("%d-%m-%Y")
        st.dataframe(selected_df[["Sl.No", "Date", "Day", "Session"]], use_container_width=True, hide_index=True)

        remove_sl = st.selectbox("Select Sl.No to remove", options=selected_df["Sl.No"].tolist(), format_func=lambda x: f"{x}")
        if st.button("Remove Selected Row", use_container_width=True):
            target_row = selected_df[selected_df["Sl.No"] == remove_sl].iloc[0]
            target_date = pd.to_datetime(target_row["Date"], dayfirst=True).date()
            target_session = target_row["Session"]
            st.session_state.selected_slots = [
                s for s in st.session_state.selected_slots
                if not (s["Date"] == target_date and s["Session"] == target_session)
            ]

    willingness_df = load_willingness()
    already_submitted = False
    if "FacultyClean" in willingness_df.columns:
        already_submitted = selected_clean in set(willingness_df["FacultyClean"].astype(str).tolist())

    st.markdown("### Submit Willingness")
    if already_submitted:
        st.warning("You have already submitted willingness.")

    remaining = max(required_count - len(st.session_state.selected_slots), 0)
    if already_submitted:
        st.info("Verification: Submission already exists for this faculty.")
    elif remaining == 0 and required_count > 0:
        st.success("Verification: Required willingness count completed. You can submit now.")
    else:
        st.info(f"Verification: Select {remaining} more option(s) to enable submission.")

    submit_disabled = already_submitted or len(st.session_state.selected_slots) != required_count
    submitted = st.button("Submit Willingness", disabled=submit_disabled, use_container_width=True)
    if submitted:
        new_rows = [
            {"Faculty": selected_name, "Date": item["Date"].strftime("%d-%m-%Y"), "Session": item["Session"]}
            for item in st.session_state.selected_slots
        ]
        out_df = pd.concat([willingness_df.drop(columns=["FacultyClean"], errors="ignore"), pd.DataFrame(new_rows)], ignore_index=True)
        out_df.to_excel(WILLINGNESS_FILE, index=False)
        st.toast("The University Examination Committee thanks you for submitting your willingness.", icon="✅")
        st.success(
            "The University Examination Committee thanks you for submitting your willingness. "
            "The final duty allocation will be carried out using AI-assisted optimization integrated with Google OR-Tools. "
            "Once finalized, the allocation will be officially communicated. Kindly check this portal regularly for updates."
        )
        st.session_state.selected_slots = []

with right:
    if designation_key == "P":
        render_month_calendars(online_df, valuation_set, "Online Duty Calendar")
    else:
        render_month_calendars(offline_df, valuation_set, "Offline Duty Calendar")

st.markdown("---")
st.markdown("Curated by Dr. N. Sathiya Narayanan | School of Mechanical Engineering")
