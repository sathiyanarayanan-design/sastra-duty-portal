import io
from typing import Optional, Tuple

import numpy as np
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Tensile Test Analyzer", layout="wide")

EXPECTED_COLUMNS = [
    "Time (sec)",
    "Extension (mm)",
    "Load (N)",
    "Tensile strain (mm/mm)",
    "Tensile stress (MPa)",
    "Tensile extension (mm)",
]

ALIASES = {
    "time": "Time (sec)",
    "time (sec)": "Time (sec)",
    "extension": "Extension (mm)",
    "extension (mm)": "Extension (mm)",
    "load": "Load (N)",
    "load (n)": "Load (N)",
    "tensile strain": "Tensile strain (mm/mm)",
    "tensile strain (mm/mm)": "Tensile strain (mm/mm)",
    "strain": "Tensile strain (mm/mm)",
    "tensile stress": "Tensile stress (MPa)",
    "tensile stress (mpa)": "Tensile stress (MPa)",
    "stress": "Tensile stress (MPa)",
    "tensile extension": "Tensile extension (mm)",
    "tensile extension (mm)": "Tensile extension (mm)",
}


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    renamed = {}
    for c in df.columns:
        key = str(c).strip().lower()
        renamed[c] = ALIASES.get(key, str(c).strip())
    df = df.rename(columns=renamed)

    # keep expected columns if present, add missing as NaN for consistent display
    for col in EXPECTED_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    return df[EXPECTED_COLUMNS]


def parse_pasted_table(text: str) -> pd.DataFrame:
    text = text.strip()
    if not text:
        return pd.DataFrame(columns=EXPECTED_COLUMNS)

    # Try CSV, TSV, then whitespace-delimited.
    for sep in [",", "\t", r"\s+"]:
        try:
            parsed = pd.read_csv(io.StringIO(text), sep=sep, engine="python")
            if parsed.shape[1] >= 2:
                return normalize_columns(parsed)
        except Exception:
            continue

    return pd.DataFrame(columns=EXPECTED_COLUMNS)


def parse_uploaded_file(uploaded_file) -> pd.DataFrame:
    if uploaded_file is None:
        return pd.DataFrame(columns=EXPECTED_COLUMNS)

    name = uploaded_file.name.lower()
    try:
        if name.endswith(".csv"):
            df = pd.read_csv(uploaded_file)
        elif name.endswith(('.xlsx', '.xls')):
            df = pd.read_excel(uploaded_file)
        elif name.endswith('.txt'):
            content = uploaded_file.getvalue().decode(errors="ignore")
            df = parse_pasted_table(content)
            return df
        else:
            content = uploaded_file.getvalue().decode(errors="ignore")
            df = parse_pasted_table(content)
            return df
    except Exception:
        return pd.DataFrame(columns=EXPECTED_COLUMNS)

    return normalize_columns(df)


def coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
    clean_df = df.copy()
    for c in EXPECTED_COLUMNS:
        clean_df[c] = pd.to_numeric(clean_df[c], errors="coerce")
    return clean_df.dropna(how="all")


def youngs_modulus_mpa(df: pd.DataFrame) -> Optional[float]:
    # Estimate from initial linear region of stress-strain curve.
    work = df[["Tensile strain (mm/mm)", "Tensile stress (MPa)"]].dropna()
    work = work[work["Tensile strain (mm/mm)"] > 0]
    if len(work) < 3:
        return None

    max_stress = work["Tensile stress (MPa)"].max()
    linear = work[
        (work["Tensile stress (MPa)"] >= 0.10 * max_stress)
        & (work["Tensile stress (MPa)"] <= 0.40 * max_stress)
    ]

    if len(linear) < 3:
        linear = work.iloc[: max(3, min(len(work), int(0.2 * len(work))))]

    x = linear["Tensile strain (mm/mm)"].to_numpy()
    y = linear["Tensile stress (MPa)"].to_numpy()

    if len(x) < 2 or np.allclose(x, x[0]):
        return None

    slope, _ = np.polyfit(x, y, 1)
    return float(slope)


def compute_metrics(df: pd.DataFrame) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    clean_df = coerce_numeric(df)
    if clean_df.empty:
        return None, None, None

    tensile_strength = clean_df["Tensile stress (MPa)"].max()
    youngs_modulus = youngs_modulus_mpa(clean_df)
    elongation = clean_df["Tensile strain (mm/mm)"].max()
    elongation_pct = None if pd.isna(elongation) else float(elongation) * 100.0

    ts = None if pd.isna(tensile_strength) else float(tensile_strength)
    return ts, youngs_modulus, elongation_pct


def metric_card(title: str, value: Optional[float], unit: str):
    if value is None:
        st.metric(title, "N/A")
    else:
        st.metric(title, f"{value:,.3f} {unit}")


st.title("Tensile Test Analyzer")
st.write(
    "Upload or paste **up to 3 datasets** for the same sample. "
    "The app calculates tensile strength, Young's modulus, and elongation at break "
    "for each dataset and also gives the average."
)

st.info(
    "Expected columns: Time (sec), Extension (mm), Load (N), Tensile strain (mm/mm), "
    "Tensile stress (MPa), Tensile extension (mm)."
)

num_datasets = st.selectbox("Number of datasets to analyze", [1, 2, 3], index=2)

all_results = []

for i in range(1, num_datasets + 1):
    st.markdown(f"---\n### Dataset {i}")
    col1, col2 = st.columns(2)

    with col1:
        uploaded = st.file_uploader(
            f"Upload Dataset {i} (CSV/XLSX/TXT)",
            type=["csv", "xlsx", "xls", "txt"],
            key=f"upload_{i}",
        )

    with col2:
        pasted = st.text_area(
            f"Or paste Dataset {i} table here",
            key=f"paste_{i}",
            height=160,
            placeholder="Paste CSV/TSV/space-separated data with headers...",
        )

    upload_df = parse_uploaded_file(uploaded)
    paste_df = parse_pasted_table(pasted) if pasted.strip() else pd.DataFrame(columns=EXPECTED_COLUMNS)

    # If both are present, combine with upload first and append pasted rows.
    combined_df = pd.concat([upload_df, paste_df], ignore_index=True)
    combined_df = normalize_columns(combined_df)

    if pasted.strip():
        st.caption(f"Pasted data preview for Dataset {i}:")
        st.dataframe(paste_df, use_container_width=True)

    if combined_df.dropna(how="all").empty:
        st.warning(f"Dataset {i}: No valid data found yet.")
        continue

    st.caption(f"Combined data used for analysis (Dataset {i}):")
    st.dataframe(combined_df, use_container_width=True)

    ts, ym, eb = compute_metrics(combined_df)
    all_results.append(
        {
            "Dataset": f"Dataset {i}",
            "Tensile strength (MPa)": ts,
            "Young's modulus (MPa)": ym,
            "Elongation at break (%)": eb,
        }
    )

if all_results:
    st.markdown("---\n## Results")
    results_df = pd.DataFrame(all_results)

    st.dataframe(results_df, use_container_width=True)

    avg_row = {
        "Dataset": "Average",
        "Tensile strength (MPa)": results_df["Tensile strength (MPa)"].mean(skipna=True),
        "Young's modulus (MPa)": results_df["Young's modulus (MPa)"].mean(skipna=True),
        "Elongation at break (%)": results_df["Elongation at break (%)"].mean(skipna=True),
    }

    st.markdown("### Average across analyzed datasets")
    c1, c2, c3 = st.columns(3)
    with c1:
        metric_card("Average Tensile strength", avg_row["Tensile strength (MPa)"], "MPa")
    with c2:
        metric_card("Average Young's modulus", avg_row["Young's modulus (MPa)"], "MPa")
    with c3:
        metric_card("Average Elongation at break", avg_row["Elongation at break (%)"], "%")

    export_df = pd.concat([results_df, pd.DataFrame([avg_row])], ignore_index=True)
    csv_bytes = export_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Download results (CSV)",
        data=csv_bytes,
        file_name="tensile_analysis_results.csv",
        mime="text/csv",
    )
else:
    st.info("Add at least one valid dataset to see results.")
