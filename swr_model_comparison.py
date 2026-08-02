"""Leakage-free SWR model comparison for hybrid filler-reinforced composites.

The script uses only the 18 experimentally measured observations supplied in the
manuscript prompt.  It compares classical statistical and machine-learning
regressors under leave-one-out cross-validation (LOOCV), creates diagnostic
figures, and exports interpolation/extrapolation predictions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import friedmanchisquare, wilcoxon
from sklearn.compose import ColumnTransformer
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LinearRegression, RidgeCV
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, LeaveOneOut, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler
from sklearn.svm import SVR

RANDOM_STATE = 42
OUTPUT_DIR = Path("swr_outputs")
FEATURES = ["load_kg", "speed_rpm", "hybrid_filler_wt_pct"]
TARGET = "swr_x1e4_mm3_per_nm"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    factory: Callable[[], Pipeline]


def load_experimental_data() -> pd.DataFrame:
    """Return only the measured BBD/control observations; no synthetic rows."""
    rows = [
        ("H1", 2, 200, 2, 0.0032, 3.42),
        ("H2", 2, 600, 2, 0.0053, 1.89),
        ("H3", 4, 200, 2, 0.0042, 2.25),
        ("H4", 4, 600, 2, 0.0058, 1.03),
        ("H5", 3, 200, 1, 0.0039, 2.78),
        ("H6", 3, 600, 1, 0.0047, 1.12),
        ("H7", 3, 200, 3, 0.0022, 1.57),
        ("H8", 3, 600, 3, 0.0027, 0.64),
        ("H9", 2, 400, 1, 0.0088, 4.70),
        ("H10", 4, 400, 1, 0.0071, 1.90),
        ("H11", 2, 400, 3, 0.0046, 2.46),
        ("H12", 4, 400, 3, 0.0056, 1.50),
        ("H13", 3, 400, 2, 0.0092, 3.28),
        ("H14", 3, 400, 2, 0.0095, 3.39),
        ("H15", 3, 400, 2, 0.0098, 3.50),
        ("C1", 2, 200, 0, 0.0052, 5.56),
        ("C2", 3, 400, 0, 0.0066, 2.35),
        ("C3", 4, 600, 0, 0.0136, 2.42),
    ]
    return pd.DataFrame(rows, columns=["sample_id", *FEATURES, "mass_loss_g", TARGET])


def build_models() -> list[ModelSpec]:
    linear_features = ColumnTransformer([("linear", "passthrough", FEATURES)])
    gpr_kernel = ConstantKernel(1.0, (1e-3, 1e3)) * Matern(nu=1.5) + WhiteKernel(noise_level=1e-3)
    return [
        ModelSpec("MLR", lambda: Pipeline([("features", linear_features), ("model", LinearRegression())])),
        ModelSpec("Polynomial_2nd_order", lambda: Pipeline([("poly", PolynomialFeatures(degree=2, include_bias=False)), ("model", RidgeCV(alphas=np.logspace(-4, 4, 25)))])),
        ModelSpec("RSM_quadratic_OLS", lambda: Pipeline([("poly", PolynomialFeatures(2, include_bias=False)), ("model", LinearRegression())])),
        ModelSpec("GPR", lambda: Pipeline([("scale", StandardScaler()), ("model", GaussianProcessRegressor(kernel=gpr_kernel, normalize_y=True, random_state=RANDOM_STATE))])),
        ModelSpec("SVR_RBF", lambda: Pipeline([("scale", StandardScaler()), ("model", SVR(kernel="rbf", C=10.0, epsilon=0.05, gamma="scale"))])),
    ]


def metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "R2": r2_score(y_true, y_pred),
        "RMSE": mean_squared_error(y_true, y_pred, squared=False),
        "MAE": mean_absolute_error(y_true, y_pred),
        "MAPE_percent": np.mean(np.abs((y_true - y_pred) / y_true)) * 100,
    }


def cross_validate_models(X: pd.DataFrame, y: pd.Series, cv) -> tuple[pd.DataFrame, pd.DataFrame]:
    predictions = []
    summary = []
    for spec in build_models():
        pred = cross_val_predict(spec.factory(), X, y, cv=cv)
        predictions.append(pd.DataFrame({"model": spec.name, "actual": y, "predicted": pred, "residual": y - pred}))
        summary.append({"model": spec.name, **metrics(y.to_numpy(), pred)})
    return pd.DataFrame(summary).sort_values("RMSE"), pd.concat(predictions, ignore_index=True)


def plot_diagnostics(predictions: pd.DataFrame) -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    for model, df in predictions.groupby("model"):
        fig, axes = plt.subplots(2, 2, figsize=(10, 8))
        axes[0, 0].scatter(df.actual, df.predicted)
        lims = [min(df.actual.min(), df.predicted.min()), max(df.actual.max(), df.predicted.max())]
        axes[0, 0].plot(lims, lims, "k--")
        axes[0, 0].set(title="Actual vs Predicted", xlabel="Actual SWR", ylabel="Predicted SWR")
        axes[0, 1].scatter(df.predicted, df.residual)
        axes[0, 1].axhline(0, color="k", linestyle="--")
        axes[0, 1].set(title="Residual plot", xlabel="Predicted SWR", ylabel="Residual")
        axes[1, 0].hist(np.abs(df.residual), bins=8)
        axes[1, 0].set(title="Absolute error distribution", xlabel="Absolute error", ylabel="Count")
        axes[1, 1].hist(df.residual, bins=8)
        axes[1, 1].set(title="Residual histogram", xlabel="Residual", ylabel="Count")
        fig.tight_layout()
        fig.savefig(OUTPUT_DIR / f"{model}_diagnostics.png", dpi=300)
        plt.close(fig)


def feature_importance_and_sensitivity(X: pd.DataFrame, y: pd.Series, best_model: str) -> None:
    model = next(spec.factory() for spec in build_models() if spec.name == best_model)
    model.fit(X, y)
    importance = permutation_importance(model, X, y, n_repeats=50, random_state=RANDOM_STATE)
    pd.DataFrame({"feature": FEATURES, "importance_mean": importance.importances_mean, "importance_std": importance.importances_std}).sort_values("importance_mean", ascending=False).to_csv(OUTPUT_DIR / "feature_importance.csv", index=False)
    baseline = X.median().to_frame().T.loc[np.repeat(0, 50)].reset_index(drop=True)
    sensitivity_frames = []
    for feature in FEATURES:
        grid = np.linspace(X[feature].min(), X[feature].max(), 50)
        probe = baseline.copy()
        probe[feature] = grid
        sensitivity_frames.append(pd.DataFrame({"feature": feature, "value": grid, "predicted_swr": model.predict(probe)}))
    pd.concat(sensitivity_frames).to_csv(OUTPUT_DIR / "sensitivity_analysis.csv", index=False)


def prediction_grids(X: pd.DataFrame, y: pd.Series, best_model: str) -> None:
    model = next(spec.factory() for spec in build_models() if spec.name == best_model)
    model.fit(X, y)
    interpolation = pd.DataFrame({
        "load_kg": [2.5, 3.0, 3.5], "speed_rpm": [300, 450, 500], "hybrid_filler_wt_pct": [1.0, 2.0, 2.5]
    })
    extrapolation = pd.DataFrame({
        "load_kg": [1.5, 4.5], "speed_rpm": [150, 700], "hybrid_filler_wt_pct": [-0.5, 3.5]
    })
    interpolation["predicted_swr"] = model.predict(interpolation)
    extrapolation["predicted_swr"] = model.predict(extrapolation)
    extrapolation["note"] = "Outside measured design space; not experimentally validated"
    interpolation.to_csv(OUTPUT_DIR / "interpolation_predictions.csv", index=False)
    extrapolation.to_csv(OUTPUT_DIR / "extrapolation_predictions.csv", index=False)


def statistical_tests(predictions: pd.DataFrame) -> pd.DataFrame:
    pivot = predictions.assign(abs_error=lambda d: d.residual.abs()).pivot(columns="model", values="abs_error")
    stat, p_value = friedmanchisquare(*[pivot[col].dropna() for col in pivot.columns])
    rows = [{"comparison": "Friedman_all_models", "statistic": stat, "p_value": p_value}]
    best = pivot.mean().idxmin()
    for col in pivot.columns:
        if col != best:
            stat, p_value = wilcoxon(pivot[best], pivot[col], zero_method="wilcox")
            rows.append({"comparison": f"Wilcoxon_{best}_vs_{col}", "statistic": stat, "p_value": p_value})
    return pd.DataFrame(rows)


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    data = load_experimental_data()
    X, y = data[FEATURES], data[TARGET]
    loocv_summary, loocv_predictions = cross_validate_models(X, y, LeaveOneOut())
    kfold_summary, _ = cross_validate_models(X, y, KFold(n_splits=5, shuffle=True, random_state=RANDOM_STATE))
    loocv_summary.to_csv(OUTPUT_DIR / "loocv_model_metrics.csv", index=False)
    kfold_summary.to_csv(OUTPUT_DIR / "five_fold_model_metrics.csv", index=False)
    loocv_predictions.to_csv(OUTPUT_DIR / "loocv_predictions.csv", index=False)
    statistical_tests(loocv_predictions).to_csv(OUTPUT_DIR / "statistical_tests.csv", index=False)
    best_model = loocv_summary.iloc[0]["model"]
    plot_diagnostics(loocv_predictions)
    feature_importance_and_sensitivity(X, y, best_model)
    prediction_grids(X, y, best_model)
    print("LOOCV metrics:\n", loocv_summary.to_string(index=False))
    print(f"\nBest LOOCV model by RMSE: {best_model}")
    print("Outputs written to", OUTPUT_DIR.resolve())


if __name__ == "__main__":
    main()
