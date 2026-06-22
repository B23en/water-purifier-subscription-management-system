"""
[Phase 2 - model 3] Random Forest train + evaluate
================================================
- Parallel ensemble, low hyperparameter sensitivity, stable (cross-check baseline)
- sklearn's RandomForest can't take category dtype directly -- the only one of
  the 4 models that needs explicit encoding (OrdinalEncoder). That difference
  itself is one of the comparison axes in the report ("categorical handling
  convenience").
- No boosting/early-stopping concept here, so we apply the equivalent
  regularization via min_samples_leaf (= min leaf sample count) and
  max_features (= column subsampling). val is folded back into train since
  RF has no use for it (test is still never touched).
Run: python train_randomforest.py
"""
import os
import sys
import time

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import OrdinalEncoder

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dataset import get_train_val_test


def train_and_evaluate(target: str = "신규", kind: str = "MoM") -> dict:
    X_train, X_val, X_test, y_train, y_val, y_test, feature_cols = get_train_val_test(target, kind)

    X_train_full = pd.concat([X_train, X_val], axis=0)
    y_train_full = pd.concat([y_train, y_val], axis=0)

    encoder = OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1)
    X_train_enc = encoder.fit_transform(X_train_full)
    X_test_enc = encoder.transform(X_test)

    model = RandomForestRegressor(
        n_estimators=300,
        max_depth=3,
        min_samples_leaf=15,
        max_features=0.7,
        random_state=42,
        n_jobs=-1,
    )

    t0 = time.time()
    model.fit(X_train_enc, y_train_full)
    train_sec = time.time() - t0

    t0 = time.time()
    pred = model.predict(X_test_enc)
    infer_sec = time.time() - t0

    rmse = float(np.sqrt(mean_squared_error(y_test, pred)))
    mae = float(mean_absolute_error(y_test, pred))
    r2 = float(r2_score(y_test, pred))

    print(f"=== Random Forest / {target} / {kind} ===")
    print(f"  train {len(X_train_full)} rows, test {len(X_test)} rows")
    print(f"  RMSE={rmse:.3f}  MAE={mae:.3f}  R2={r2:.3f}")
    print(f"  train_sec={train_sec:.2f}s  infer_sec={infer_sec:.3f}s")

    return {
        "model": "RandomForest", "target": target, "kind": kind,
        "rmse": rmse, "mae": mae, "r2": r2,
        "train_sec": train_sec, "infer_sec": infer_sec,
    }


if __name__ == "__main__":
    train_and_evaluate()
