"""
[Phase 2 common] train/val/test split utilities
================================================
- Converts the delta dataset from data_loader.build_dataset() into model-ready splits
- Time-based split: most recent N months (기준월) held out as test
  (per project plan: last 6 months)
- All 4 models (XGBoost/LightGBM/RandomForest/CatBoost) must use this same
  function for a fair comparison
Run (standalone check): python dataset.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import build_dataset, segment_cols_for


def get_train_test(target: str = "신규", kind: str = "MoM", test_months: int = 6):
    """Returns: X_train, X_test, y_train, y_test, feature_cols
    Features are category dtype (encoding handled per-model in each training script)"""
    ds = build_dataset(target, kind)
    feature_cols = segment_cols_for(target)

    months = sorted(ds["기준월"].unique())
    test_set = set(months[-test_months:])
    train_mask = ~ds["기준월"].isin(test_set)

    X = ds[feature_cols].copy()
    for c in feature_cols:
        X[c] = X[c].astype("category")
    y = ds["Δ계정수"]

    X_train, X_test = X[train_mask], X[~train_mask]
    y_train, y_test = y[train_mask], y[~train_mask]
    return X_train, X_test, y_train, y_test, feature_cols


def get_train_val_test(target: str = "신규", kind: str = "MoM",
                        test_months: int = 6, val_months: int = 6):
    """Same as get_train_test but also carves a validation tail for early stopping.
    - test:  most recent test_months months (final evaluation, never used in training)
    - val:   the val_months months immediately before test (early-stopping signal only)
    - train: everything before that
    Returns: X_train, X_val, X_test, y_train, y_val, y_test, feature_cols"""
    ds = build_dataset(target, kind)
    feature_cols = segment_cols_for(target)

    months = sorted(ds["기준월"].unique())
    test_set = set(months[-test_months:])
    remaining = [m for m in months if m not in test_set]
    val_set = set(remaining[-val_months:])
    train_set = set(remaining) - val_set

    X = ds[feature_cols].copy()
    for c in feature_cols:
        X[c] = X[c].astype("category")
    y = ds["Δ계정수"]

    train_mask = ds["기준월"].isin(train_set)
    val_mask = ds["기준월"].isin(val_set)
    test_mask = ds["기준월"].isin(test_set)

    return (
        X[train_mask], X[val_mask], X[test_mask],
        y[train_mask], y[val_mask], y[test_mask],
        feature_cols,
    )


if __name__ == "__main__":
    X_train, X_test, y_train, y_test, cols = get_train_test()
    print(f"train: {len(X_train)} rows / test: {len(X_test)} rows / {len(cols)} features")

    X_tr, X_val, X_te, y_tr, y_val, y_te, _ = get_train_val_test()
    print(f"(early-stop split) train: {len(X_tr)} / val: {len(X_val)} / test: {len(X_te)}")
