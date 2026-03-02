import os, re, random
from collections import defaultdict
import pandas as pd

random.seed(42)

# ─────────────────────────── PATHS ──────────────────────────── #
UPLOAD_DIR      = "/mnt/user-data/uploads"
FACULTY_INIT    = os.path.join(UPLOAD_DIR, "Faculty_with_initials.xlsx")
WILL_FILE       = os.path.join(UPLOAD_DIR, "IG_Willingness.xlsx")
# These may or may not exist – we derive required counts from the willingness file itself
FACULTY_MASTER  = os.path.join(UPLOAD_DIR, "Faculty_Master.xlsx")

OUT_DIR         = "/mnt/user-data/outputs"
os.makedirs(OUT_DIR, exist_ok=True)

# ─────────────────────── DESIGNATION RULES ──────────────────── #
DUTY_RULES = {
    "P":   3,
    "ACP": 5,
    "SAP": 7,
    "AP3": 7,
    "AP2": 7,
    "TA":  9,
    "RA":  9,
}
DEFAULT_DUTY_COUNT = 5   # fallback if designation not found

# ─────────────────────── LOAD FACULTY MAP ────────────────────── #
fac_df = pd.read_excel(FACULTY_INIT)
fac_df.columns = ["Name", "Initials"]

# Build initials -> Name  (handle trailing commas, leading spaces, case)
init_to_name = {}
for _, row in fac_df.iterrows():
    name = str(row["Name"]).strip()
    raw  = str(row["Initials"]).strip() if pd.notna(row["Initials"]) else ""
    key  = raw.strip(" ,")
    if key and key.lower() != "nan":
        init_to_name[key] = name
        init_to_name[key.lower()] = name   # case-insensitive fallback

# Also build name -> designation from Faculty_Master if available
name_to_desig = {}
if os.path.exists(FACULTY_MASTER):
    fm = pd.read_excel(FACULTY_MASTER)
    fm.columns = fm.columns.str.strip()
    if len(fm.columns) >= 2:
        fm.rename(columns={fm.columns[0]: "Name", fm.columns[1]: "Designation"}, inplace=True)
        for _, r in fm.iterrows():
            name_to_desig[str(r["Name"]).strip().lower()] = str(r["Designation"]).strip().upper()

all_faculty_names = [str(r["Name"]).strip() for _, r in fac_df.iterrows()]

# ─────────────────────── PARSE WILLINGNESS FILE ──────────────── #
raw = pd.read_excel(WILL_FILE, header=None)

def parse_section(raw_df, start_row, end_row, duty_type):
    """Parse a contiguous block of date/session/required/initials rows."""
    rows = []
    for idx in range(start_row, end_row):
        row = raw_df.iloc[idx]
        date_val   = row.iloc[0]
        session    = str(row.iloc[1]).strip().upper() if pd.notna(row.iloc[1]) else ""
        required   = row.iloc[2]
        initials_r = str(row.iloc[3]).strip() if pd.notna(row.iloc[3]) else ""

        if pd.isna(date_val) or session not in ("FN", "AN"):
            continue
        try:
            date = pd.to_datetime(date_val, dayfirst=True).date()
        except Exception:
            continue
        try:
            req = int(float(required))
        except Exception:
            req = 1

        # Parse initials list – split on comma, handle compound entries
        raw_parts = [p.strip() for p in initials_r.split(",") if p.strip()]
        clean_parts = []
        for p in raw_parts:
            # Handle "S.Balaganesh. Ezekiel E" type compound
            if ". " in p and len(p) > 6:
                # try splitting on ". "
                sub = [s.strip() for s in p.split(". ") if s.strip()]
                # Only split if each sub part looks like an initial/name token
                resolved = []
                for s in sub:
                    if s.rstrip(".") in init_to_name or s.rstrip(".").lower() in init_to_name:
                        resolved.append(s.rstrip("."))
                    else:
                        resolved.append(s)
                clean_parts.extend(resolved)
            elif "." in p and len(p) <= 4:
                # "PSS.KMN" type – split on dot
                clean_parts.extend([x for x in p.split(".") if x])
            else:
                clean_parts.append(p)

        # Map initials to names
        names_willing = []
        for token in clean_parts:
            token_clean = token.strip(" ,.")
            if not token_clean:
                continue
            # Direct lookup
            name = init_to_name.get(token_clean) or init_to_name.get(token_clean.lower())
            # Try stripped of trailing period
            if not name:
                name = init_to_name.get(token_clean.rstrip("."))
            # Try case-insensitive
            if not name:
                for k, v in init_to_name.items():
                    if k.lower() == token_clean.lower():
                        name = v
                        break
            if name:
                names_willing.append(name)
            else:
                # Keep original token as-is for reporting
                names_willing.append(f"[UNMAPPED:{token_clean}]")

        rows.append({
            "Date":     date,
            "Session":  session,
            "Required": req,
            "Willing":  names_willing,
            "Type":     duty_type,
        })
    return rows

# Detect section boundaries
offline_start, offline_end = 1, None
online_start,  online_end  = None, None

for i in range(len(raw)):
    cell = str(raw.iloc[i, 0]).strip()
    if "GCR Online" in cell or "Online exams" in cell.lower():
        offline_end  = i
        online_start = i + 2   # skip header row
        online_end   = len(raw)
        break

if offline_end is None:
    offline_end = len(raw)

slots_offline = parse_section(raw, offline_start, offline_end, "Offline")
slots_online  = []
if online_start and online_end:
    slots_online = parse_section(raw, online_start, online_end, "Online")

all_slots = slots_offline + slots_online

print(f"Parsed {len(slots_offline)} offline slots, {len(slots_online)} online slots")

# ─────────────────────── DUTY COUNT RULES ────────────────────── #
def required_duties_for(name):
    key = name.strip().lower()
    desig = name_to_desig.get(key, "")
    return DUTY_RULES.get(desig, DEFAULT_DUTY_COUNT)

# ─────────────────────── ALLOCATOR ───────────────────────────── #
# Track how many duties each faculty has been assigned
assigned_count  = defaultdict(int)    # name -> count
assigned_slots  = []                   # list of dicts for final output
# Track which (name, date, session) already assigned to avoid duplicates
assigned_set    = set()

# For each slot, collect willing faculty (excluding unmapped)
def get_willing(slot):
    return [n for n in slot["Willing"] if not n.startswith("[UNMAPPED:")]

# Priority: 1) willing faculty sorted by fewest assignments
# 2) if not enough willing, pull from all eligible faculty (not on same date, under quota)

def faculty_eligible_for_fallback(name, date, session, duty_type):
    """Check if a faculty can be assigned as fallback (not already on same date)."""
    # Not already assigned on same date (any session)
    for (n, d, s) in assigned_set:
        if n == name and d == date:
            return False
    return True

# Build date-session exclusions per faculty from valuation / other constraints
# (We don't have valuation file here, so we just avoid double-booking same date)

# Sort slots by required count descending (fill harder slots first)
all_slots_sorted = sorted(all_slots, key=lambda x: -x["Required"])

unmet_slots = []

for slot in all_slots_sorted:
    date    = slot["Date"]
    session = slot["Session"]
    req     = slot["Required"]
    dtype   = slot["Type"]
    willing = get_willing(slot)

    # Sort willing by current assigned count (fewest first = fairness)
    willing_sorted = sorted(willing, key=lambda n: assigned_count[n])

    chosen = []
    used   = set()

    # Phase 1: assign from willing pool
    for name in willing_sorted:
        if len(chosen) >= req:
            break
        if name in used:
            continue
        if (name, date, session) in assigned_set:
            continue
        # Don't assign same person twice on same date
        already_today = any((name, date, s) in assigned_set for s in ["FN", "AN"])
        if already_today:
            continue
        chosen.append(name)
        used.add(name)

    # Phase 2: fallback from all faculty if still short
    if len(chosen) < req:
        # Filter to eligible faculty, preferring those with fewer duties
        eligible_fallback = [
            n for n in all_faculty_names
            if n not in used
            and not any((n, date, s) in assigned_set for s in ["FN", "AN"])
            and faculty_eligible_for_fallback(n, date, session, dtype)
        ]
        # Prefer those with lower assigned count
        eligible_fallback.sort(key=lambda n: assigned_count[n])
        for name in eligible_fallback:
            if len(chosen) >= req:
                break
            chosen.append(name)
            used.add(name)

    # Record assignments
    for name in chosen:
        assigned_count[name] += 1
        assigned_set.add((name, date, session))
        allocated_by = "Willingness" if name in willing else "Auto-Assigned"
        assigned_slots.append({
            "Name":         name,
            "Date":         date,
            "Session":      session,
            "Type":         dtype,
            "Allocated_By": allocated_by,
        })

    shortfall = req - len(chosen)
    if shortfall > 0:
        unmet_slots.append({
            "Date":     date,
            "Session":  session,
            "Type":     dtype,
            "Required": req,
            "Assigned": len(chosen),
            "Shortfall":shortfall,
        })

# ─────────────────────── OUTPUTS ──────────────────────────────── #

# Final Allocation
alloc_df = pd.DataFrame(assigned_slots)
alloc_df["Date"] = pd.to_datetime(alloc_df["Date"]).dt.strftime("%d-%m-%Y")
alloc_df = alloc_df.sort_values(["Date", "Session", "Name"]).reset_index(drop=True)
alloc_df.insert(0, "Sl.No", alloc_df.index + 1)
alloc_out = os.path.join(OUT_DIR, "Final_Allocation.xlsx")
alloc_df.to_excel(alloc_out, index=False)
print(f"Saved: {alloc_out}  ({len(alloc_df)} rows)")

# Per-faculty summary
summary_rows = []
for name in all_faculty_names:
    req_duties = required_duties_for(name)
    assigned   = assigned_count.get(name, 0)
    rows_f     = alloc_df[alloc_df["Name"] == name]
    will_pct   = f"{len(rows_f[rows_f['Allocated_By']=='Willingness'])} / {assigned}" if assigned > 0 else "0/0"
    desig      = name_to_desig.get(name.strip().lower(), "N/A")
    summary_rows.append({
        "Name":             name,
        "Designation":      desig,
        "Required_Duties":  req_duties,
        "Assigned_Duties":  assigned,
        "Gap":              max(req_duties - assigned, 0),
        "Willingness_Used": will_pct,
    })

summary_df = pd.DataFrame(summary_rows).sort_values("Gap", ascending=False)

# Unmet slots
unmet_df = pd.DataFrame(unmet_slots) if unmet_slots else pd.DataFrame(
    columns=["Date","Session","Type","Required","Assigned","Shortfall"])

# Write report with two sheets
report_out = os.path.join(OUT_DIR, "Allocation_Report.xlsx")
with pd.ExcelWriter(report_out, engine="openpyxl") as writer:
    summary_df.to_excel(writer, sheet_name="Faculty_Summary", index=False)
    unmet_df.to_excel(writer, sheet_name="Unmet_Slots", index=False)
    alloc_df.to_excel(writer, sheet_name="Full_Allocation", index=False)

print(f"Saved: {report_out}")

# Print quick stats
print(f"\n{'='*50}")
print(f"Total assignments : {len(alloc_df)}")
print(f"Willingness-based : {len(alloc_df[alloc_df['Allocated_By']=='Willingness'])}")
print(f"Auto-assigned     : {len(alloc_df[alloc_df['Allocated_By']=='Auto-Assigned'])}")
print(f"Unmet slots       : {len(unmet_df)}")
if len(unmet_df) > 0:
    print("\nUnmet slots:")
    print(unmet_df.to_string(index=False))

print(f"\nFaculty with shortfall in required duties:")
gaps = summary_df[summary_df["Gap"] > 0][["Name","Designation","Required_Duties","Assigned_Duties","Gap"]]
if len(gaps):
    print(gaps.to_string(index=False))
else:
    print("  None – all faculty fulfilled!")

# Unmapped initials report
print("\n=== Unmapped initials in willingness file ===")
unmapped = set()
for slot in all_slots:
    for n in slot["Willing"]:
        if n.startswith("[UNMAPPED:"):
            unmapped.add(n)
if unmapped:
    for u in sorted(unmapped):
        print(" ", u)
else:
    print("  None")

# ─────────────────────── SECOND PASS: Fill duty gaps ──────────── #
# For faculty who have not yet met required duty count, assign to open slots

def get_gap(name):
    req = required_duties_for(name)
    return max(req - assigned_count.get(name, 0), 0)

under_assigned = [n for n in all_faculty_names if get_gap(n) > 0]
under_assigned.sort(key=get_gap, reverse=True)

available_slots_sorted = sorted(all_slots, key=lambda x: (x["Date"], x["Session"]))
second_pass_rows = []

for name in under_assigned:
    for slot in available_slots_sorted:
        if get_gap(name) <= 0:
            break
        date    = slot["Date"]
        session = slot["Session"]
        dtype   = slot["Type"]
        already_today = any((name, date, s) in assigned_set for s in ["FN", "AN"])
        if already_today:
            continue
        if (name, date, session) in assigned_set:
            continue
        assigned_count[name] += 1
        assigned_set.add((name, date, session))
        second_pass_rows.append({
            "Name":         name,
            "Date":         date,
            "Session":      session,
            "Type":         dtype,
            "Allocated_By": "Gap-Fill",
        })

if second_pass_rows:
    assigned_slots.extend(second_pass_rows)
    print(f"Second pass gap-fill added {len(second_pass_rows)} assignments")

# ─────────────── RE-RUN OUTPUT GENERATION ─────────────────────── #
alloc_df = pd.DataFrame(assigned_slots)
alloc_df["Date"] = pd.to_datetime(alloc_df["Date"]).dt.strftime("%d-%m-%Y")
alloc_df = alloc_df.sort_values(["Date", "Session", "Name"]).reset_index(drop=True)
alloc_df.insert(0, "Sl.No", alloc_df.index + 1)
alloc_df.to_excel(alloc_out, index=False)
print(f"Updated Final_Allocation.xlsx  ({len(alloc_df)} rows total)")

summary_rows2 = []
for name in all_faculty_names:
    req_duties = required_duties_for(name)
    assigned   = assigned_count.get(name, 0)
    rows_f     = alloc_df[alloc_df["Name"] == name]
    w = len(rows_f[rows_f["Allocated_By"] == "Willingness"])
    g = len(rows_f[rows_f["Allocated_By"] == "Gap-Fill"])
    a = len(rows_f[rows_f["Allocated_By"] == "Auto-Assigned"])
    desig = name_to_desig.get(name.strip().lower(), "N/A")
    summary_rows2.append({
        "Name":              name,
        "Designation":       desig,
        "Required_Duties":   req_duties,
        "Assigned_Duties":   assigned,
        "From_Willingness":  w,
        "Auto_Assigned":     a,
        "Gap_Filled":        g,
        "Remaining_Gap":     max(req_duties - assigned, 0),
    })

summary_df2 = pd.DataFrame(summary_rows2).sort_values("Remaining_Gap", ascending=False)

with pd.ExcelWriter(report_out, engine="openpyxl") as writer:
    summary_df2.to_excel(writer, sheet_name="Faculty_Summary", index=False)
    unmet_df.to_excel(writer, sheet_name="Unmet_Slots", index=False)
    alloc_df.to_excel(writer, sheet_name="Full_Allocation", index=False)

print(f"Updated Allocation_Report.xlsx")
print(f"\n{'='*55}")
print(f"FINAL STATS")
print(f"{'='*55}")
print(f"Total assignments   : {len(alloc_df)}")
print(f"  From willingness  : {len(alloc_df[alloc_df['Allocated_By']=='Willingness'])}")
print(f"  Auto-assigned     : {len(alloc_df[alloc_df['Allocated_By']=='Auto-Assigned'])}")
print(f"  Gap-filled        : {len(alloc_df[alloc_df['Allocated_By']=='Gap-Fill'])}")
print(f"Unmet duty slots    : {len(unmet_df)}")
gaps2 = summary_df2[summary_df2["Remaining_Gap"] > 0][["Name","Required_Duties","Assigned_Duties","Remaining_Gap"]]
print(f"Faculty still short : {len(gaps2)}")
if len(gaps2):
    print(gaps2.to_string(index=False))
