"""
[Dashboard] 세그먼트 요인분석 (기여도 직접 분석 연결)
================================================================
- models/segment_shap/segment_contribution.py 의 순수 계산 함수를 재사용한다.
  · 전체기간 트렌드: rank_segment_cols / build_monthly_delta / compute_contribution
  · 특정 월(MoM/YoY): load_raw + _shift_month 로 analyze_month 로직을 데이터-반환형으로 재구성
- CLI용 run()/analyze_month()는 print+PNG 부작용이 있어 직접 호출하지 않는다.
- 데이터는 WATER_BASE_DIR 환경변수로 주입(모델 코드가 강제). summary_dir 상위를 세팅해 재사용.
"""
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

# 요인분석 대상 (누적은 비대상)
ALLOWED_TARGETS = {"신규", "해지", "만기"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _show_df(df: pd.DataFrame):
    """object 컬럼을 문자열로 캐스팅해 Arrow 직렬화 경고 없이 표시."""
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object:
            out[c] = out[c].astype(str)
    st.dataframe(out, use_container_width=True, hide_index=True)


def _import_segment():
    """segment_contribution 모듈을 격리 import 한다.

    models/segment_shap/config.py·data_loader.py 는 앱의 PythonCode/config.py 와
    모듈명이 겹친다. 앱이 먼저 `config` 를 로드해 두므로, 그대로 import 하면
    segment_contribution 내부의 `from config import ...` 가 앱 config 를 잡아 실패한다.
    → import 동안만 sys.modules 의 config/data_loader 를 임시로 비우고, 끝나면 복원한다.
    (segment_contribution 은 한 번 import 되면 필요한 값/함수를 자체 보유하므로 복원해도 안전)
    """
    import importlib

    if "segment_contribution" in sys.modules:
        return sys.modules["segment_contribution"]

    seg_dir = str(_repo_root() / "models" / "segment_shap")
    saved_config = sys.modules.pop("config", None)
    saved_data_loader = sys.modules.pop("data_loader", None)
    sys.path.insert(0, seg_dir)
    try:
        mod = importlib.import_module("segment_contribution")
    finally:
        # seg_dir 를 sys.path 에서 전부 제거한다.
        # (segment_contribution.py·data_loader.py 가 스스로 sys.path.insert 하므로
        #  중복 등록될 수 있고, 남겨두면 이후 앱 재실행 시 from config import BASE_DIR 가
        #  models/segment_shap/config.py 를 잡아 앱 전체가 깨진다.)
        while seg_dir in sys.path:
            sys.path.remove(seg_dir)
        # 앱의 config/data_loader 복원 (없었으면 models 것 제거)
        if saved_config is not None:
            sys.modules["config"] = saved_config
        else:
            sys.modules.pop("config", None)
        if saved_data_loader is not None:
            sys.modules["data_loader"] = saved_data_loader
        else:
            sys.modules.pop("data_loader", None)
    return mod


def _ensure_importable(summary_dir: Path) -> str:
    base_dir = str(Path(summary_dir).parent)  # SummaryDB 의 상위 = 데이터 루트
    os.environ["WATER_BASE_DIR"] = base_dir
    _import_segment()  # 격리 import 선수행
    return base_dir


# =========================================================
# 캐시된 계산 (모두 DataFrame/dict 반환 → 캐시 가능)
# =========================================================
@st.cache_data(show_spinner=False)
def _rank(target: str, base_dir: str) -> pd.DataFrame:
    os.environ["WATER_BASE_DIR"] = base_dir
    mod = _import_segment()
    return mod.rank_segment_cols(target)


@st.cache_data(show_spinner=False)
def _contrib(target: str, seg_col: str, base_dir: str) -> pd.DataFrame:
    os.environ["WATER_BASE_DIR"] = base_dir
    mod = _import_segment()
    pivot = mod.build_monthly_delta(target, seg_col)
    return mod.compute_contribution(pivot)


@st.cache_data(show_spinner=False)
def _month_analysis(target: str, month: str, base_dir: str):
    """analyze_month 의 데이터-반환형. (mom_total, yoy_total, {seg_col: df}, 누락안내)."""
    os.environ["WATER_BASE_DIR"] = base_dir
    mod = _import_segment()
    load_raw = mod.load_raw
    _shift_month = mod._shift_month
    SEGMENT_COLS = mod.SEGMENT_COLS
    CANCEL_EXTRA_COL = mod.CANCEL_EXTRA_COL
    DOMINANCE_THRESHOLD = mod.DOMINANCE_THRESHOLD

    prev_month = _shift_month(month, -1)
    yoy_month = _shift_month(month, -12)

    df = load_raw(target)
    available = set(df["년월"].unique())
    latest = max(available) if available else "?"
    for m, label in [(month, "선택 월"), (prev_month, "전달"), (yoy_month, "전년동월")]:
        if m not in available:
            return None, None, {}, (
                f"{label}({m}) 데이터가 없습니다. (현재 데이터는 {latest}까지 있습니다)"
            )

    def month_total(m):
        return float(df[df["년월"] == m]["계정수"].sum())

    cur_total = month_total(month)
    mom_total = cur_total - month_total(prev_month)
    yoy_total = cur_total - month_total(yoy_month)

    cols = list(SEGMENT_COLS) + ([CANCEL_EXTRA_COL] if target == "해지" else [])
    results = {}
    for col in cols:
        agg = df.groupby([col, "년월"], observed=True)["계정수"].sum().reset_index()

        def grp_count(m):
            return agg[agg["년월"] == m].set_index(col)["계정수"]

        cur, prev, yoy = grp_count(month), grp_count(prev_month), grp_count(yoy_month)
        all_grp = cur.index.union(prev.index).union(yoy.index)
        cur = cur.reindex(all_grp).fillna(0)
        prev = prev.reindex(all_grp).fillna(0)
        yoy = yoy.reindex(all_grp).fillna(0)

        mom_d, yoy_d = cur - prev, cur - yoy
        mom_abs, yoy_abs = mom_d.abs().sum(), yoy_d.abs().sum()
        mom_share = (mom_d.abs() / mom_abs * 100) if mom_abs > 0 else mom_d * 0
        yoy_share = (yoy_d.abs() / yoy_abs * 100) if yoy_abs > 0 else yoy_d * 0

        col_df = pd.DataFrame({
            "group": all_grp,
            "yoy_delta": yoy_d.values,
            "yoy_share": yoy_share.values.round(1),
            "mom_delta": mom_d.values,
            "mom_share": mom_share.values.round(1),
        }).sort_values("yoy_share", ascending=False).reset_index(drop=True)
        col_df["is_dominated"] = col_df["yoy_share"] >= DOMINANCE_THRESHOLD

        meaningful = col_df[~col_df["is_dominated"]].head(6)
        if not meaningful.empty:
            results[(month, col)] = col_df  # 튜플 키는 캐시 후 dict 로 그대로 반환
    # 튜플 키 → seg_col 키로 평탄화
    flat = {k[1]: v for k, v in results.items()}
    return mom_total, yoy_total, flat, None


# =========================================================
# 렌더링
# =========================================================
def _render_trend(target: str, base_dir: str):
    mod = _import_segment()
    MIN_CORR = mod.MIN_CORR
    DOMINANCE_THRESHOLD = mod.DOMINANCE_THRESHOLD

    with st.spinner("세그먼트 컬럼별 기여도 분석 중..."):
        col_rank = _rank(target, base_dir)

    dominated = col_rank[col_rank["is_dominated"]]
    meaningful = col_rank[~col_rank["is_dominated"] & (col_rank["top1_corr"] >= MIN_CORR)]

    st.markdown("### 실질 분석 대상 — 변화를 주도하는 세그먼트")
    if meaningful.empty:
        st.info("실질 분석 대상 컬럼이 없습니다.")
    else:
        show = meaningful[["seg_col", "top1_group", "top1_share_pct", "top1_corr", "top1_mean_abs"]].copy()
        show.columns = ["세그먼트(축)", "Top1 그룹", "비중(%)", "상관", "평균|Δ|"]
        _show_df(show)

    with st.expander(f"구조적 지배 (비중 ≥ {DOMINANCE_THRESHOLD:.0f}% — 분석 의미 낮아 제외)"):
        if dominated.empty:
            st.caption("해당 없음")
        else:
            d = dominated[["seg_col", "top1_group", "top1_share_pct"]].copy()
            d.columns = ["세그먼트(축)", "Top1 그룹", "비중(%)"]
            _show_df(d)

    # 상위 3개 컬럼 상세
    focus = meaningful.head(3)["seg_col"].tolist() or col_rank.head(2)["seg_col"].tolist()
    for seg_col in focus:
        st.markdown(f"#### [{seg_col}] 그룹별 기여도")
        contrib = _contrib(target, seg_col, base_dir)
        groups = contrib[contrib["share_pct"] < DOMINANCE_THRESHOLD].head(8)
        if groups.empty:
            st.caption("표시할 그룹이 없습니다.")
            continue

        tbl = groups[["group", "share_pct", "mean_abs_delta", "corr_with_total", "mean_direction"]].copy()
        tbl.columns = ["그룹", "비중(%)", "평균|Δ|", "상관", "방향(평균Δ)"]
        _show_df(tbl)

        fig, ax = plt.subplots(figsize=(9, max(2.2, 0.5 * len(groups))))
        colors = ["#E74C3C" if v < 0 else "#3498DB" for v in groups["mean_direction"]]
        ax.barh(groups["group"][::-1], groups["mean_direction"][::-1], color=colors[::-1])
        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_xlabel("평균 Δ계정수 (− 감소 / + 증가)")
        ax.set_title(f"{target} · {seg_col} — 그룹별 평균 변화 방향")
        plt.tight_layout()
        st.pyplot(fig)
        plt.close(fig)


def _render_month(target: str, base_dir: str, default_month: str):
    # 챗봇 딥링크가 세션에 월을 주입할 수 있으므로, 기본값은 세션에 한 번만 심고
    # 위젯에는 value= 를 주지 않는다(Session State + value 동시 지정 경고 방지).
    month_key = f"seg_month_{target}"
    if month_key not in st.session_state:
        st.session_state[month_key] = default_month
    month = st.text_input("분석할 연월 (YYYY.MM)", key=month_key).strip()
    try:
        pd.Period(month.replace(".", "-"), freq="M")
    except Exception:
        st.error("연월 형식이 올바르지 않습니다. 예: 2024.03")
        return

    with st.spinner(f"{month} 월 분석 중..."):
        mom_total, yoy_total, results, err = _month_analysis(target, month, base_dir)
    if err:
        st.warning(err)
        return

    c1, c2 = st.columns(2)
    c1.metric("전달 대비 (MoM)", f"{mom_total:+,.0f} 계정")
    c2.metric("전년동월 대비 (YoY)", f"{yoy_total:+,.0f} 계정")
    st.caption("아래는 YoY(전년동월) 기준 기여도 상위 세그먼트입니다. 비중 ≥ 80%(구조적 지배)는 제외했습니다.")

    if not results:
        st.info("표시할 세그먼트 결과가 없습니다.")
        return

    for seg_col, col_df in list(results.items())[:6]:
        meaningful = col_df[~col_df["is_dominated"]].head(6)
        if meaningful.empty:
            continue
        st.markdown(f"#### [{seg_col}]")
        tbl = meaningful[["group", "yoy_delta", "yoy_share", "mom_delta", "mom_share"]].copy()
        tbl.columns = ["그룹", "YoY Δ", "YoY 비중(%)", "MoM Δ", "MoM 비중(%)"]
        _show_df(tbl)


def render_dashboard(context: dict):
    data_type = context.get("data_type")
    summary_dir = Path(context["summary_dir"])

    st.markdown("## 🔍 세그먼트 요인분석")
    st.caption("어떤 세그먼트 그룹이 변화를 주도했는지 — 비중 / 상관 / 변화 방향으로 직접 측정")

    if data_type not in ALLOWED_TARGETS:
        st.info(f"'{data_type}'는 요인분석 대상이 아닙니다.")
        return
    if not summary_dir.exists():
        st.error(f"요약 DB 폴더가 없습니다: {summary_dir}")
        return

    base_dir = _ensure_importable(summary_dir)

    mode = st.radio(
        "분석 모드", ["전체기간 트렌드", "특정 월 (MoM/YoY)"],
        horizontal=True, key=f"seg_mode_{data_type}",
    )

    if mode == "전체기간 트렌드":
        _render_trend(data_type, base_dir)
    else:
        default_month = context.get("end_month") or "2024.03"
        _render_month(data_type, base_dir, default_month)
