# SWR Modeling Workflow for the Manuscript

This repository includes `swr_model_comparison.py`, a leakage-free analysis script for comparing classical statistical modeling and machine learning models for specific wear rate (SWR) prediction.

## Dataset policy

The script embeds exactly the 18 experimentally measured observations supplied in the prompt: H1-H15 and C1-C3. It does not generate, augment, interpolate into the training data, apply Gaussian noise, use Latin Hypercube Sampling, or perform SMOTE-style oversampling.

## Models compared

The workflow compares five model families under the same validation protocol:

1. Multiple Linear Regression (MLR)
2. Second-order Polynomial Regression
3. Response Surface Methodology (RSM) as quadratic ordinary least squares
4. Gaussian Process Regression (GPR)
5. Support Vector Regression (SVR, RBF kernel)

Polynomial regression and RSM are intentionally kept as separate named pipelines so their manuscript outputs can be discussed separately. The RSM pipeline is the unregularized quadratic OLS surface commonly reported for Box-Behnken response-surface studies, while the polynomial regression pipeline uses ridge regularization to improve numerical stability in the small-sample setting.

## Validation and leakage control

Leave-One-Out Cross Validation (LOOCV) is the primary validation method. Optional shuffled 5-fold CV is also exported as a secondary check. Every model is implemented as a scikit-learn `Pipeline`, so preprocessing steps such as `StandardScaler` for GPR and SVR are fitted only on the training fold inside each CV iteration.

## Outputs

Running the script creates `swr_outputs/` with:

- `loocv_model_metrics.csv`: R², RMSE, MAE, and MAPE from LOOCV.
- `five_fold_model_metrics.csv`: secondary 5-fold CV metrics.
- `loocv_predictions.csv`: actual, predicted, and residual values for every held-out sample.
- Diagnostic figures for each model: actual-vs-predicted, residual plot, absolute-error distribution, and residual histogram.
- `feature_importance.csv`: permutation feature importance for the best LOOCV model.
- `sensitivity_analysis.csv`: one-factor-at-a-time sensitivity trends across the measured design range.
- `interpolation_predictions.csv`: predictions at new points inside the experimental design space.
- `extrapolation_predictions.csv`: predictions outside the design space, explicitly flagged as not experimentally validated.
- `statistical_tests.csv`: Friedman test across absolute errors and Wilcoxon signed-rank comparisons between the best model and the alternatives.

## Discussion points for the manuscript

For this small BBD dataset, the most defensible model is not necessarily the one with the lowest apparent training error. LOOCV performance should drive the model ranking because each prediction is made for a sample that was excluded from model fitting. If RSM or MLR is competitive with GPR/SVR, that outcome supports a classical modeling choice because lower-complexity models are more interpretable and less prone to instability with only 18 observations.

RSM is particularly appropriate when the goal is mechanistic interpretation of load, speed, filler content, and their curvature/interactions inside a designed experimental region. Machine-learning methods such as GPR and SVR can capture nonlinearities without specifying an equation form, but their flexibility may not be fully justified with such a small dataset. Their extrapolated predictions should be treated cautiously because they are not constrained by new wear experiments outside the measured factor ranges.

Recommended future work includes adding replicate measurements across the design space, validating the selected model on an independent experimental campaign, reporting uncertainty intervals, and expanding the factor space only through additional controlled experiments rather than synthetic sample generation.
