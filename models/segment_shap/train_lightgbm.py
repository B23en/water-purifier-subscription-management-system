"""
[Phase 2 - model 2] LightGBM train + evaluate
================================================
- Leaf-wise growth, fast training. Uses pandas category dtype directly
  (LightGBM auto-detects category dtype -- no manual encoding needed)
- Same regularization philosophy as XGBoost: early stopping + bagging
  (subsample) + minimum leaf sample count, since most segment combos appear
  in only 1-2 months (sparse data) and overfit very easily.
Run: python train_lightgbm.py
"""
import os
import sys
import time

import numpy as np
import lightgbm as lgb
from lightgbm import LGBMRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dataset import get_train_val_test


def train_and_evaluate(target: str = "신규", kind: str = "MoM") -> dict:
    X_train, X_val, X_test, y_train, y_val, y_test, feature_cols = get_train_val_test(target, kind)

    model = LGBMRegressor(
        n_estimators=1000,
        max_depth=3,
        learning_rate=0.03,
        min_child_samples=30,
        subsample=0.7,
        subsample_freq=1,
        colsample_bytree=0.7,
        reg_lambda=3,
        random_state=42,
        verbose=-1,
    )

    t0 = time.time()
    model.fit(
        X_train, y_train,
        eval_set=[(X_val, y_val)],
        categorical_feature=feature_cols,
        callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)],
    )
    train_sec = time.time() - t0

    t0 = time.time()
    pred = model.predict(X_test)
    infer_sec = time.time() - t0

    rmse = float(np.sqrt(mean_squared_error(y_test, pred)))
    mae = float(mean_absolute_error(y_test, pred))
    r2 = float(r2_score(y_test, pred))

    print(f"=== LightGBM / {target} / {kind} ===")
    print(f"  train {len(X_train)} rows, test {len(X_test)} rows, trees used={model.best_iteration_}")
    print(f"  RMSE={rmse:.3f}  MAE={mae:.3f}  R2={r2:.3f}")
    print(f"  train_sec={train_sec:.2f}s  infer_sec={infer_sec:.3f}s")

    return {
        "model": "LightGBM", "target": target, "kind": kind,
        "rmse": rmse, "mae": mae, "r2": r2,
        "train_sec": train_sec, "infer_sec": infer_sec,
    }


if __name__ == "__main__":
    train_and_evaluate()
