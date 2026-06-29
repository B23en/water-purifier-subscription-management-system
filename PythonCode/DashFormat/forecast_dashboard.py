"""
[Dashboard] 다음달 예측 (forecaster 운영 인터페이스 연결)
================================================================
- models/forecast/forecaster.py 의 forecast() 를 호출해 다음달 예측값 + 신뢰구간을 표시.
- 챔피언 모델: 신규=ARIMA(1,1,1), 재구독률=ARIMA(1,1,1), 해지=ETS(damped HW).
- 데이터는 WATER_BASE_DIR 환경변수로 주입(모델 코드가 강제). 여기서는 앱의
  summary_dir(=BASE_DIR/SummaryDB)의 상위 폴더를 WATER_BASE_DIR 로 세팅해 재사용한다.
- forecaster 는 ARIMA/ETS 적합 + 18-step 백테스트로 무거우므로 결과를 st.cache_data 로 캐시.
"""
import os
import sys
from pathlib import Path

import numpy as np
import streamlit as st
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

# data_type 탭 → 예측 대상 목록 (만기/누적은 예측 대상 아님)
TARGETS_BY_TYPE = {
    "신규": ["신규", "재구독률"],
    "해지": ["해지"],
}

# 비율(%) 타깃 — 표시 단위 구분용
RATE_TARGETS = {"재구독률"}


def _repo_root() -> Path:
    # 이 파일: <repo>/PythonCode/DashFormat/forecast_dashboard.py
    return Path(__file__).resolve().parents[2]


def _ensure_forecast_importable(summary_dir: Path):
    """WATER_BASE_DIR 주입 + models/forecast 를 import 경로에 추가."""
    base_dir = str(Path(summary_dir).parent)  # SummaryDB 의 상위 = 데이터 루트
    os.environ["WATER_BASE_DIR"] = base_dir
    forecast_dir = str(_repo_root() / "models" / "forecast")
    if forecast_dir not in sys.path:
        sys.path.insert(0, forecast_dir)
    return base_dir


@st.cache_data(show_spinner=False)
def _compute(target: str, base_dir: str):
    """forecast(target) 결과 + 과거 시계열 반환. (target, base_dir) 로 캐시."""
    os.environ["WATER_BASE_DIR"] = base_dir
    from forecaster import forecast
    from train_models import load_series

    result = forecast(target)
    months, values = load_series(target)
    return result, list(months), [float(v) for v in values]


def _plot_forecast(target: str, months, values, result: dict, recent: int = 24):
    """최근 실측 추이 + 다음달 예측점 + 신뢰구간 밴드."""
    m = months[-recent:]
    y = values[-recent:]
    x = list(range(len(m)))

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.plot(x, y, marker="o", linewidth=2, color="#1f77b4", label="실측")

    # 다음달 예측점 (x = 마지막 실측 다음 위치)
    fx = len(m)
    point = result["prediction"]
    lower = result["lower"]
    upper = result["upper"]

    ax.errorbar(
        fx, point,
        yerr=[[point - lower], [upper - point]],
        fmt="o", color="#d62728", capsize=6, linewidth=2,
        label=f"다음달 예측 ({result['interval_conf']}% 구간)",
    )
    # 마지막 실측 → 예측점 연결 점선
    ax.plot([x[-1], fx], [y[-1], point], linestyle="--", color="#d62728", linewidth=1.5)
    ax.annotate(
        f"{point:,.1f}",
        (fx, point), textcoords="offset points", xytext=(8, 0),
        va="center", fontsize=10, color="#d62728", fontweight="bold",
    )

    labels = [f"{str(p).split('.')[0][-2:]}.{str(p).split('.')[1]}" if "." in str(p) else str(p) for p in m]
    labels.append("예측")
    ax.set_xticks(list(range(len(m) + 1)))
    ax.set_xticklabels(labels, rotation=45, fontsize=8)
    unit = "%" if target in RATE_TARGETS else "건"
    ax.set_ylabel(f"{target} ({unit})")
    ax.set_title(f"{target} — 최근 {recent}개월 추이 + 다음달 예측")
    ax.legend(loc="upper left", frameon=False)
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)


def _render_target(target: str, base_dir: str):
    try:
        result, months, values = _compute(target, base_dir)
    except Exception as e:
        st.error(f"[{target}] 예측 실패: {e}")
        return

    is_rate = target in RATE_TARGETS
    unit = "%" if is_rate else "건"
    fmt = (lambda v: f"{v:,.1f}{unit}") if is_rate else (lambda v: f"{v:,.0f}{unit}")

    st.markdown(f"### {target} — 다음달 예측")

    c1, c2, c3 = st.columns([1.2, 1, 1])
    with c1:
        st.metric(label=f"다음달 예측값 ({target})", value=fmt(result["prediction"]))
    with c2:
        st.metric(label=f"{result['interval_conf']}% 신뢰구간 하한", value=fmt(result["lower"]))
    with c3:
        st.metric(label=f"{result['interval_conf']}% 신뢰구간 상한", value=fmt(result["upper"]))

    st.caption(
        f"모델: {result['model']} · 기준월: {result['last_month']} · "
        f"1-step 오차 RMSE: {result['error_rmse']} · 백테스트 표본 n={result['n_backtest']}"
        + ("  ⚠ 구간이 0~100 경계에서 잘림" if result.get("clipped") else "")
    )
    st.caption(
        "※ 신뢰구간은 최근 18개월 1-step 백테스트 오차 기반의 경험적 추정으로, "
        "다음달(1개월) 예측에만 유효한 운영용 가늠자입니다."
    )

    _plot_forecast(target, months, values, result)


def render_dashboard(context: dict):
    data_type = context.get("data_type")
    summary_dir = Path(context["summary_dir"])

    st.markdown("## 🔮 다음달 예측")

    targets = TARGETS_BY_TYPE.get(data_type)
    if not targets:
        st.info(f"'{data_type}'는 예측 대상이 아닙니다. (만기는 계약기간 기반 확정 계산, 누적은 예측 비대상)")
        return

    if not summary_dir.exists():
        st.error(f"요약 DB 폴더가 없습니다: {summary_dir}")
        return

    base_dir = _ensure_forecast_importable(summary_dir)

    for i, target in enumerate(targets):
        if i > 0:
            st.markdown("---")
        _render_target(target, base_dir)
