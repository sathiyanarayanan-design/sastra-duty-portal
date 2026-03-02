"""
SASTRA SoME – Examination Duty Allocator
=========================================
Uses Google OR-Tools CP-SAT solver to produce a fair, constraint-satisfying
duty allocation from faculty willingness data.

Input files (same folder as script):
  Faculty_Master.xlsx      – Name | Designation | V1..V5 (valuation dates)
  Final_Willingness.xlsx   – Faculty | Date | Session
  Offline_Duty.xlsx        – Date | Session | Required
  Online_Duty.xlsx         – Date | Session | Required

Output file:
  Final_Allocation.xlsx    – Faculty | Date | Session | Mode (Offline/Online)

Run:
  pip install ortools openpyxl pandas
  python allocate_duty.py
"""

import os
import sys
import pandas as pd
from ortools.sat.python import cp_model

# ─────────────────────────── CONFIG ───────────────────────────
FACULTY_FILE      = "Faculty_Master.xlsx"
WILLINGNESS_FILE  = "Final_Willingness.xlsx"
OFFLINE_FILE      = "Offline_Duty.xlsx"
ONLINE_FILE       = "Online_Duty.xlsx"
OUTPUT_FILE       = "Final_Allocation.xlsx"

# Designation → required duty count
DUTY_QUOTA = {
    "P":   3,   # Professor  → online only
    "ACP": 5,   # Assoc Prof → 1 online + remaining offline
    "SAP": 7,
    "AP3": 7,
    "AP2": 7,
    "TA":  9,
    "RA":  9,
}

# ─────────────────────────── HELPERS ──────────────────────────
def clean(x):
    return str(x).strip().lower()

def norm_session(v):
    t = str(v).strip().upper()
    if t in {"FN","FORENOON","MORNING","AM"}: return "FN"
    if t in {"AN","AFTERNOON","EVENING","PM"}: return "AN"
    return t

def load(path):
    if not os.path.exists(path):
        sys.exit(f"ERROR: {path} not found.")
    return pd.read_excel(path)

def norm_duty(df):
    df = df.copy(); df.columns = df.columns.str.strip()
    df.rename(columns={df.columns[0]:"Date", df.columns[1]:"Session",
                        df.columns[2]:"Required"}, inplace=True)
    df["Date"]     = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df             = df.dropna(subset=["Date"])
    df["Session"]  = df["Session"].apply(norm_session)
    df["Required"] = pd.to_numeric(df["Required"], errors="coerce").fillna(1).astype(int)
    return df

def valuation_dates(row):
    dates = set()
    for col in ["V1","V2","V3","V4","V5"]:
        if col in row.index and pd.notna(row[col]):
            dates.add(pd.to_datetime(row[col], dayfirst=True).date())
    return dates

# ─────────────────────────── LOAD DATA ────────────────────────
print("Loading data …")
faculty_df = load(FACULTY_FILE)
faculty_df.columns = faculty_df.columns.str.strip()
faculty_df.rename(columns={faculty_df.columns[0]:"Name",
                            faculty_df.columns[1]:"Designation"}, inplace=True)
faculty_df["Clean"] = faculty_df["Name"].apply(clean)
faculty_df["DesKey"] = faculty_df["Designation"].astype(str).str.strip().str.upper()

will_df = load(WILLINGNESS_FILE)
will_df.columns = will_df.columns.str.strip()
will_df["Date"]    = pd.to_datetime(will_df["Date"], dayfirst=True, errors="coerce")
will_df            = will_df.dropna(subset=["Date"])
will_df["Session"] = will_df["Session"].apply(norm_session)
will_df["Clean"]   = will_df["Faculty"].apply(clean)

offline_df = norm_duty(load(OFFLINE_FILE))
online_df  = norm_duty(load(ONLINE_FILE))

# ─────────────────────── BUILD SLOT DEMAND ────────────────────
# slot_demand: { (date, session, mode) -> required_count }
slot_demand = {}
for _, r in offline_df.iterrows():
    key = (r["Date"].date(), r["Session"], "Offline")
    slot_demand[key] = slot_demand.get(key, 0) + int(r["Required"])
for _, r in online_df.iterrows():
    key = (r["Date"].date(), r["Session"], "Online")
    slot_demand[key] = slot_demand.get(key, 0) + int(r["Required"])

all_slots = sorted(slot_demand.keys())   # (date, session, mode)
print(f"  Total slots: {len(all_slots)}")

# ─────────────────────── BUILD FACULTY LIST ───────────────────
faculties = []
for _, row in faculty_df.iterrows():
    des = row["DesKey"]
    quota = DUTY_QUOTA.get(des, 0)
    if quota == 0:
        print(f"  WARN: unknown designation '{des}' for {row['Name']} – skipping")
        continue

    val_dates = valuation_dates(row)
    fc = row["Clean"]

    # Slots this faculty is willing for
    will_rows = will_df[will_df["Clean"] == fc]
    willing_set = set()
    for _, wr in will_rows.iterrows():
        willing_set.add((wr["Date"].date(), wr["Session"]))

    # Which modes apply?
    if des == "P":
        allowed_modes = {"Online"}
    elif des == "ACP":
        allowed_modes = {"Offline", "Online"}   # 1 online + rest offline enforced later
    else:
        allowed_modes = {"Offline"}

    faculties.append({
        "name":         row["Name"],
        "clean":        fc,
        "des":          des,
        "quota":        quota,
        "val_dates":    val_dates,
        "willing_set":  willing_set,
        "allowed_modes":allowed_modes,
    })

print(f"  Faculty loaded: {len(faculties)}")

# ─────────────────── BUILD CP-SAT MODEL ───────────────────────
print("Building CP-SAT model …")
model  = cp_model.CpModel()

# x[f][s] = 1 if faculty f is assigned to slot s
x = {}
for fi, fac in enumerate(faculties):
    for si, slot in enumerate(all_slots):
        date, session, mode = slot
        # Hard feasibility gates
        if date in fac["val_dates"]:
            continue                         # valuation conflict
        if mode not in fac["allowed_modes"]:
            continue                         # mode not applicable
        x[(fi, si)] = model.new_bool_var(f"x_{fi}_{si}")

# ── Constraint 1: Each slot must be filled exactly (soft penalty if short) ──
# We use an optional slack so the solver doesn't become infeasible
slot_slack = {}
for si, slot in enumerate(all_slots):
    demand = slot_demand[slot]
    assigned = [x[(fi, si)] for fi, _ in enumerate(faculties) if (fi, si) in x]
    if not assigned:
        print(f"  WARN: No eligible faculty for slot {slot} – will be unfilled")
        continue
    slack = model.new_int_var(0, demand, f"slack_{si}")
    slot_slack[si] = slack
    model.add(sum(assigned) + slack == demand)

# ── Constraint 2: Each faculty assigned exactly their quota ──
faculty_slack = {}
for fi, fac in enumerate(faculties):
    assigned = [x[(fi, si)] for si in range(len(all_slots)) if (fi, si) in x]
    if not assigned:
        continue
    under = model.new_int_var(0, fac["quota"], f"under_{fi}")
    over  = model.new_int_var(0, fac["quota"], f"over_{fi}")
    faculty_slack[fi] = (under, over)
    model.add(sum(assigned) - over + under == fac["quota"])

# ── Constraint 3: No faculty in same date both FN and AN ──
from collections import defaultdict
faculty_date_sessions = defaultdict(list)
for (fi, si), var in x.items():
    date, session, mode = all_slots[si]
    faculty_date_sessions[(fi, date)].append(var)

for (fi, date), vars_list in faculty_date_sessions.items():
    if len(vars_list) > 1:
        model.add(sum(vars_list) <= 1)

# ── Constraint 4: ACP – exactly 1 online duty ──
for fi, fac in enumerate(faculties):
    if fac["des"] == "ACP":
        online_vars = [x[(fi, si)] for si, slot in enumerate(all_slots)
                       if slot[2] == "Online" and (fi, si) in x]
        if online_vars:
            model.add(sum(online_vars) == 1)

# ── Objective: maximise willingness match, minimise slack ──
willingness_score = []
for (fi, si), var in x.items():
    date, session, mode = all_slots[si]
    fac = faculties[fi]
    if (date, session) in fac["willing_set"]:
        willingness_score.append(var)

slot_penalty   = sum(slot_slack.values()) if slot_slack else 0
faculty_penalty= sum(u + o for u, o in faculty_slack.values()) if faculty_slack else 0

model.maximize(
    10 * sum(willingness_score)
    - 50 * slot_penalty
    - 20 * faculty_penalty
)

# ─────────────────────────── SOLVE ────────────────────────────
print("Solving (this may take a few seconds) …")
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = 120
solver.parameters.num_search_workers  = 4
status = solver.solve(model)

status_name = solver.status_name(status)
print(f"  Solver status: {status_name}")
if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
    sys.exit("ERROR: No feasible solution found. Check demand vs faculty count.")

# ─────────────────────── EXTRACT RESULTS ──────────────────────
records = []
for (fi, si), var in x.items():
    if solver.value(var) == 1:
        date, session, mode = all_slots[si]
        fac = faculties[fi]
        willingness_match = (date, session) in fac["willing_set"]
        records.append({
            "Faculty":           fac["name"],
            "Designation":       fac["des"],
            "Date":              date.strftime("%d-%m-%Y"),
            "Session":           session,
            "Mode":              mode,
            "Willingness_Match": "Yes" if willingness_match else "No (Force-Assigned)",
        })

result_df = pd.DataFrame(records).sort_values(["Date","Session","Mode","Faculty"])
result_df.to_excel(OUTPUT_FILE, index=False)
print(f"\n✅ Allocation saved to {OUTPUT_FILE}")

# ─────────────────────────── REPORT ───────────────────────────
print("\n── Allocation Summary ──")
total = len(result_df)
will_match = (result_df["Willingness_Match"] == "Yes").sum()
print(f"  Total assignments      : {total}")
print(f"  Willingness matched    : {will_match} ({will_match/total*100:.1f}%)")
print(f"  Force-assigned         : {total - will_match}")

print("\n── Unfilled Slots ──")
unfilled = []
for si, slot in enumerate(all_slots):
    demand = slot_demand[slot]
    assigned_count = sum(
        solver.value(x[(fi, si)])
        for fi in range(len(faculties)) if (fi, si) in x
    )
    if assigned_count < demand:
        unfilled.append({
            "Date":    slot[0].strftime("%d-%m-%Y"),
            "Session": slot[1],
            "Mode":    slot[2],
            "Required":demand,
            "Assigned":assigned_count,
            "Shortfall":demand - assigned_count,
        })

if unfilled:
    uf_df = pd.DataFrame(unfilled)
    print(uf_df.to_string(index=False))
    uf_df.to_excel("Unfilled_Slots.xlsx", index=False)
    print("  ⚠ Unfilled slots saved to Unfilled_Slots.xlsx")
else:
    print("  All slots fully filled! ✅")

print("\n── Per-Faculty Duty Count ──")
counts = result_df.groupby(["Faculty","Designation"]).size().reset_index(name="Assigned")
for _, row in counts.iterrows():
    quota = DUTY_QUOTA.get(row["Designation"], "?")
    match = "✅" if row["Assigned"] == quota else "⚠"
    print(f"  {match} {row['Faculty']:35s} [{row['Designation']}] {row['Assigned']}/{quota}")
