"""
[Phase 4] STL seasonal decomposition
================================================
- Decomposes the aggregate monthly total (Trend/Seasonal/Residual) for each of
  신규/해지/만기, separately from the segment-level regression+SHAP work above.
- period=12 (annual seasonality), needs >=24 months (we have 77~81)
- Residuals outside the IQR fence are flagged as outliers
Run: python stl_analysis.py
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

import numpy as np
import pandas as pd
from statsmodels.tsa.seasonal import STL

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import load_raw

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stl_outputs")


def monthly_total(target: str) -> pd.Series:
    """target(신규/해지/만기)의 전체 합계 월별 시계열."""
    df = load_raw(target)
    s = df.groupby("년월")["계정수"].sum().sort_index()
    return s


def run_stl(target: str = "신규", period: int = 12):
    os.makedirs(OUT_DIR, exist_ok=True)
    s = monthly_total(target)
    if len(s) < period * 2:
        raise ValueError(f"{target}: STL needs >= {period*2} months, have {len(s)}")

    res = STL(s.values, period=period, robust=True).fit()
    trend, seasonal, resid = res.trend, res.seasonal, res.resid
    months = s.index.tolist()

    # IQR-based residual outliers
    q1, q3 = np.percentile(resid, [25, 75])
    iqr = q3 - q1
    lower, upper = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    outlier_mask = (resid < lower) | (resid > upper)

    print(f"=== STL / {target} (period={period}, {len(s)} months) ===")
    print(f"residual IQR fence: [{lower:.1f}, {upper:.1f}]")
    for m, r in zip(np.array(months)[outlier_mask], resid[outlier_mask]):
        print(f"  outlier: {m}  resid={r:+.1f}")

    # Seasonal index by calendar month (avg across years)
    cal_month = [int(m.split(".")[1]) for m in months]
    seasonal_index = pd.Series(seasonal, index=cal_month).groupby(level=0).mean().sort_index()
    print("\nseasonal index by calendar month (avg):")
    print(seasonal_index.round(1).to_string())

    fig, axes = plt.subplots(4, 1, figsize=(12, 9), sharex=True)
    x = np.arange(len(months))
    axes[0].plot(x, s.values); axes[0].set_ylabel("원본")
    axes[1].plot(x, trend); axes[1].set_ylabel("Trend")
    axes[2].plot(x, seasonal); axes[2].set_ylabel("Seasonal")
    axes[3].plot(x, resid)
    axes[3].scatter(x[outlier_mask], resid[outlier_mask], color="red", zorder=5)
    axes[3].axhline(lower, color="gray", linestyle="--", linewidth=0.8)
    axes[3].axhline(upper, color="gray", linestyle="--", linewidth=0.8)
    axes[3].set_ylabel("Residual")

    tick_idx = list(range(0, len(months), 6))
    axes[3].set_xticks(tick_idx)
    axes[3].set_xticklabels([months[i] for i in tick_idx], rotation=90, fontsize=7)

    fig.suptitle(f"STL decomposition -- {target} (monthly total)")
    fig.tight_layout()
    out_path = os.path.join(OUT_DIR, f"stl_{target}.png")
    fig.savefig(out_path, dpi=120)
    plt.close(fig)
    print(f"\nsaved: {out_path}")

    return {"months": months, "trend": trend, "seasonal": seasonal, "resid": resid,
            "outliers": list(zip(np.array(months)[outlier_mask], resid[outlier_mask]))}


if __name__ == "__main__":
    for target in ["신규", "해지", "만기"]:
        run_stl(target)
        print()
