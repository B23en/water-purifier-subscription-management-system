"""
[Phase 3] SHAP analysis
================================================
- Uses TreeExplainer to find which segments push Delta-account-count up or down
- R2 is near 0 across all 4 models, so this is NOT a high-confidence predictive
  explanation -- treat it as a reference signal for "which segment the model
  leans on most", not a confirmed causal driver.
- Model: LightGBM (same regularized config as train_lightgbm.py). XGBoost was
  tried first but shap 0.49 can't parse XGBoost 3.x's base_score format
  (known compatibility bug) -- LightGBM's TreeExplainer support is stable and
  the two models perform almost identically anyway (see Phase 2 comparison).
Run: python shap_analysis.py
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Windows에서 한글이 깨지지 않도록 폰트 지정 (없으면 기본 폰트로 조용히 무시)
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False
import numpy as np
import pandas as pd
import shap
import lightgbm as lgb
from lightgbm import LGBMRegressor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dataset import get_train_val_test

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shap_outputs")


def _train_model(target, kind):
    X_train, X_val, X_test, y_train, y_val, y_test, feature_cols = get_train_val_test(target, kind)
    model = LGBMRegressor(
        n_estimators=1000, max_depth=3, learning_rate=0.03, min_child_samples=30,
        subsample=0.7, subsample_freq=1, colsample_bytree=0.7, reg_lambda=3,
        random_state=42, verbose=-1,
    )
    model.fit(
        X_train, y_train, eval_set=[(X_val, y_val)], categorical_feature=feature_cols,
        callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)],
    )
    return model, X_test, y_test, feature_cols


def run_shap(target: str = "신규", kind: str = "MoM", top_n: int = 5):
    os.makedirs(OUT_DIR, exist_ok=True)
    model, X_test, y_test, feature_cols = _train_model(target, kind)

    explainer = shap.TreeExplainer(model)
    shap_values = explainer.shap_values(X_test)

    # 1) global importance (mean |SHAP|)
    mean_abs = np.abs(shap_values).mean(axis=0)
    importance = pd.Series(mean_abs, index=feature_cols).sort_values(ascending=False)
    print(f"=== SHAP global importance / {target} / {kind} ===")
    print(importance.to_string())

    plt.figure(figsize=(7, 4))
    importance.sort_values().plot.barh()
    plt.xlabel("mean |SHAP value| (impact on Delta-account-count)")
    plt.title(f"Segment importance -- {target}/{kind}")
    plt.tight_layout()
    out_path = os.path.join(OUT_DIR, f"shap_importance_{target}_{kind}.png")
    plt.savefig(out_path, dpi=120)
    plt.close()
    print(f"saved: {out_path}")

    # 2) direction (+/-) by category, for the top features
    top_feats = importance.index[:top_n]
    for feat in top_feats:
        col_idx = feature_cols.index(feat)
        df = pd.DataFrame({
            feat: X_test[feat].values,
            "shap": shap_values[:, col_idx],
        })
        cat_effect = df.groupby(feat, observed=True)["shap"].mean().dropna().sort_values()
        print(f"\n--- {feat}: mean SHAP by category (bottom/top 5) ---")
        print("[pushes Delta down the most]")
        print(cat_effect.head(5).to_string())
        print("[pushes Delta up the most]")
        print(cat_effect.tail(5).to_string())

    return importance


if __name__ == "__main__":
    run_shap()
