"""
[Phase 2 결과물] 4모델 x 3타깃 x 2비교방식 성능 결과표
================================================
- 신규/해지/만기 각각, MoM/YoY 각각에 대해 4개 모델을 동일 조건으로 학습·평가하고
  결과를 한 표로 모은다.
실행: python compare_models.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import train_catboost
import train_lightgbm
import train_randomforest
import train_xgboost

RUNNERS = {
    "XGBoost": train_xgboost.train_and_evaluate,
    "LightGBM": train_lightgbm.train_and_evaluate,
    "RandomForest": train_randomforest.train_and_evaluate,
    "CatBoost": train_catboost.train_and_evaluate,
}


def run_all(targets=("신규", "해지", "만기"), kinds=("MoM", "YoY")):
    rows = []
    for target in targets:
        for kind in kinds:
            for name, fn in RUNNERS.items():
                r = fn(target, kind)
                rows.append(r)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = run_all()
    cols = ["target", "kind", "model", "rmse", "mae", "r2", "train_sec", "infer_sec"]
    df = df[cols].sort_values(["target", "kind", "rmse"])
    pd.set_option("display.width", 140)
    print()
    print(df.to_string(index=False))
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_comparison_result.csv")
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\n저장: {out_path}")
