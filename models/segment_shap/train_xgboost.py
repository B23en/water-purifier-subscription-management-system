"""
[Phase 2 - model 1] XGBoost train + evaluate
================================================
- Baseline model from design doc; baseline for the 4-model comparison.
- Categorical features kept as pandas category dtype + enable_categorical=True
  (no manual label encoding -- XGBoost 2.x recommended approach)
- Most segment combos appear in only 1-2 months (sparse data) -> overfits easily
  (measured: depth=5, n_estimators=300 defaults dropped R2 to -0.10).
  Regularized via early stopping + subsampling + min leaf size -- same philosophy
  applied to all 4 models for a fair comparison.
Run: python train_xgboost.py
"""
import os
import sys
import time

import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dataset import get_train_val_test


def train_and_evaluate(target: str = "신규", kind: str = "MoM") -> dict:
    X_train, X_val, X_test, y_train, y_val, y_test, feature_cols = get_train_val_test(target, kind)

    model = XGBRegressor(
        n_estimators=1000,
        max_depth=3,
        learning_rate=0.03,
        min_child_weight=15,
        subsample=0.7,
        colsample_bytree=0.7,
        reg_lambda=3,
        enable_categorical=True,
        tree_method="hist",
        early_stopping_rounds=30,
        random_state=42,
    )

    t0 = time.time()
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
    train_sec = time.time() - t0

    t0 = time.time()
    pred = model.predict(X_test)
    infer_sec = time.time() - t0

    rmse = float(np.sqrt(mean_squared_error(y_test, pred)))
    mae = float(mean_absolute_error(y_test, pred))
    r2 = float(r2_score(y_test, pred))

    print(f"=== XGBoost / {target} / {kind} ===")
    print(f"  train {len(X_train)} rows, test {len(X_test)} rows, trees used={model.best_iteration}")
    print(f"  RMSE={rmse:.3f}  MAE={mae:.3f}  R2={r2:.3f}")
    print(f"  train_sec={train_sec:.2f}s  infer_sec={infer_sec:.3f}s")

    return {
        "model": "XGBoost", "target": target, "kind": kind,
        "rmse": rmse, "mae": mae, "r2": r2,
        "train_sec": train_sec, "infer_sec": infer_sec,
    }


if __name__ == "__main__":
    train_and_evaluate()
