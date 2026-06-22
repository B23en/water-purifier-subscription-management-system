"""
[Phase 2 - model 4] CatBoost train + evaluate
================================================
- Handles categorical variables natively, no label/one-hot encoding needed
  (just pass cat_features)
- CatBoost's defaults already include some regularization (ordered boosting),
  which is part of why it overfits less than the others by default. For a fair
  comparison we apply the same explicit regularization philosophy as the other
  3 models (early stopping + subsampling + min leaf sample count).
Run: python train_catboost.py
"""
import os
import sys
import time

import numpy as np
from catboost import CatBoostRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dataset import get_train_val_test


def train_and_evaluate(target: str = "신규", kind: str = "MoM") -> dict:
    X_train, X_val, X_test, y_train, y_val, y_test, feature_cols = get_train_val_test(target, kind)

    # CatBoost can't take pandas category dtype directly; cast to str (representation only, not encoding)
    X_train_cb = X_train.astype(str)
    X_val_cb = X_val.astype(str)
    X_test_cb = X_test.astype(str)

    model = CatBoostRegressor(
        n_estimators=1000,
        depth=3,
        learning_rate=0.03,
        min_data_in_leaf=15,
        l2_leaf_reg=3,
        bootstrap_type="Bernoulli",
        subsample=0.7,
        rsm=0.7,
        random_state=42,
        cat_features=feature_cols,
        early_stopping_rounds=30,
        verbose=False,
    )

    t0 = time.time()
    model.fit(X_train_cb, y_train, eval_set=(X_val_cb, y_val))
    train_sec = time.time() - t0

    t0 = time.time()
    pred = model.predict(X_test_cb)
    infer_sec = time.time() - t0

    rmse = float(np.sqrt(mean_squared_error(y_test, pred)))
    mae = float(mean_absolute_error(y_test, pred))
    r2 = float(r2_score(y_test, pred))

    print(f"=== CatBoost / {target} / {kind} ===")
    print(f"  train {len(X_train)} rows, test {len(X_test)} rows, trees used={model.get_best_iteration()}")
    print(f"  RMSE={rmse:.3f}  MAE={mae:.3f}  R2={r2:.3f}")
    print(f"  train_sec={train_sec:.2f}s  infer_sec={infer_sec:.3f}s")

    return {
        "model": "CatBoost", "target": target, "kind": kind,
        "rmse": rmse, "mae": mae, "r2": r2,
        "train_sec": train_sec, "infer_sec": infer_sec,
    }


if __name__ == "__main__":
    train_and_evaluate()
