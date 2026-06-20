import re
from pathlib import Path

import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm


# ✅ 한글 폰트
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False


# ---------------------------------------------------------
# 공통 유틸
# ---------------------------------------------------------
def format_net_value(val):
    if pd.isna(val):
        return ""
    return f"{val:,.0f}"


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = (
        df.columns.astype(str)
        .str.replace("\ufeff", "", regex=False)
        .str.replace('"', "", regex=False)
        .str.replace("'", "", regex=False)
        .str.strip()
    )
    return df


def normalize_month_series(series: pd.Series) -> pd.Series:
    return pd.to_datetime(
        series.astype(str)
        .str.replace(".", "-", regex=False)
        .str.strip(),
        errors="coerce"
    )


def detect_value_col(df: pd.DataFrame) -> str:
    """
    계정수 컬럼 자동 탐지
    """
    candidates = ["계정수", "신규계정수", "해지계정수", "만기계정수"]
    for c in candidates:
        if c in df.columns:
            return c
    raise ValueError(f"계정수 컬럼을 찾을 수 없습니다. 현재 컬럼: {list(df.columns)}")


def extract_month_from_filename(file_name: str):
    """
    파일명에서 yyyy.mm / yyyy-mm / yyyymm 추출
    """
    stem = Path(file_name).stem
    m = re.search(r"(20\d{2})[.\-_]?(\d{2})", stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


def load_monthly_metric(
    summary_dir: Path,
    prefix: str,
    month_col_name: str,
    output_col_name: str,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp
) -> pd.DataFrame:
    """
    SummaryDB의 신규/해지/만기 parquet를 월별 집계해서 가져옴
    결과 컬럼:
    기준월, output_col_name
    """
    files = sorted(summary_dir.glob(f"{prefix}_*.parquet"))

    if not files:
        return pd.DataFrame(columns=["기준월", output_col_name])

    all_frames = []

    for fp in files:
        try:
            df = pd.read_parquet(fp)
            df = normalize_columns(df)

            # 기준월 컬럼 처리
            if month_col_name in df.columns:
                df["기준월"] = normalize_month_series(df[month_col_name])
            elif "기준월" in df.columns:
                df["기준월"] = normalize_month_series(df["기준월"])
            else:
                inferred = extract_month_from_filename(fp.name)
                if inferred is None:
                    continue
                df["기준월"] = pd.to_datetime(inferred, errors="coerce")

            value_col = detect_value_col(df)
            df[value_col] = pd.to_numeric(df[value_col], errors="coerce").fillna(0)

            df = df[(df["기준월"] >= start_dt) & (df["기준월"] <= end_dt)]

            if df.empty:
                continue

            month_sum = (
                df.groupby("기준월", as_index=False)[value_col]
                .sum()
                .rename(columns={value_col: output_col_name})
            )

            all_frames.append(month_sum)

        except Exception:
            # 개별 파일 오류는 건너뛰고 계속 진행
            continue

    if not all_frames:
        return pd.DataFrame(columns=["기준월", output_col_name])

    result = pd.concat(all_frames, ignore_index=True)
    result = (
        result.groupby("기준월", as_index=False)[output_col_name]
        .sum()
        .sort_values("기준월")
    )
    return result


def build_pivot_with_yearly_cumulative(table_df: pd.DataFrame) -> pd.DataFrame:
    """
    월별 컬럼 + 연도별 누적 컬럼을 함께 가지는 Pivot 생성

    행:
    신규계정수, 해지계정수, 만기계정수, 순증계정수, 누적계정수

    열:
    25.01, 25.02, ..., 25년 누적, 26.01, 26.02, ..., 26년 누적
    """
    row_order = ["신규계정수", "해지계정수", "만기계정수", "순증계정수", "누적계정수"]

    # 월 정렬 보장
    temp = table_df.copy().sort_values("기준월")

    # 표시용 컬럼
    temp["월표시"] = temp["기준월"].dt.strftime("%y.%m")
    temp["연도"] = temp["기준월"].dt.year

    pivot_display = pd.DataFrame(index=row_order)

    # 1) 월별 컬럼 먼저 구성
    for _, row in temp.iterrows():
        month_label = row["월표시"]
        for r in row_order:
            pivot_display.loc[r, month_label] = row[r]

    # 2) 연도별 누적 컬럼 추가
    final = pd.DataFrame(index=row_order)

    years = list(dict.fromkeys(temp["연도"].tolist()))  # 순서 유지

    for year in years:
        year_df = temp[temp["연도"] == year].copy()

        # 월별 컬럼 추가
        for _, row in year_df.iterrows():
            month_label = row["월표시"]
            final[month_label] = pivot_display[month_label]

        # 연도 누적 컬럼 계산
        year_label = f"{str(year)[2:]}년 누적"

        year_sum = {
            "신규계정수": year_df["신규계정수"].sum(),
            "해지계정수": year_df["해지계정수"].sum(),
            "만기계정수": year_df["만기계정수"].sum(),
            "순증계정수": year_df["순증계정수"].sum(),
            "누적계정수": year_df["누적계정수"].iloc[-1],  # 마지막 월 누적계정수
        }

        for r in row_order:
            final.loc[r, year_label] = year_sum[r]

    return final


# ---------------------------------------------------------
# 메인 Dashboard
# ---------------------------------------------------------
def render_dashboard(context):

    summary_dir = Path(context["summary_dir"])
    start_month = context["start_month"]
    end_month = context["end_month"]

    cumulative_path = summary_dir / "누적_년월.parquet"

    if not cumulative_path.exists():
        st.error("❌ 누적_년월.parquet 파일이 없습니다.")
        return

    # -------------------------------------------------
    # 누적 데이터 로드
    # -------------------------------------------------
    df = pd.read_parquet(cumulative_path)
    df = normalize_columns(df)

    required_cols = ["기준월", "누적계정수", "순증계정수"]
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        st.error(f"❌ 누적 파일 필수 컬럼이 없습니다: {missing_cols}")
        return

    df["기준월"] = normalize_month_series(df["기준월"])

    start_dt = pd.to_datetime(start_month.replace(".", "-"), errors="coerce")
    end_dt = pd.to_datetime(end_month.replace(".", "-"), errors="coerce")

    if pd.isna(start_dt) or pd.isna(end_dt):
        st.error("❌ 조회 기간 형식이 올바르지 않습니다. 예: 2025.01")
        return

    df = df[(df["기준월"] >= start_dt) & (df["기준월"] <= end_dt)]

    if df.empty:
        st.warning("조회 기간 데이터 없음")
        return

    # -------------------------------------------------
    # 누적 / 순증 월별 집계
    # -------------------------------------------------
    monthly = (
        df.groupby("기준월", as_index=False)[["누적계정수", "순증계정수"]]
        .sum()
        .sort_values("기준월")
    )

    # -------------------------------------------------
    # 신규 / 해지 / 만기 월별 집계 추가 로드
    # -------------------------------------------------
    monthly_new = load_monthly_metric(
        summary_dir=summary_dir,
        prefix="신규",
        month_col_name="계약시작월",
        output_col_name="신규계정수",
        start_dt=start_dt,
        end_dt=end_dt,
    )

    monthly_term = load_monthly_metric(
        summary_dir=summary_dir,
        prefix="해지",
        month_col_name="해지완료월",
        output_col_name="해지계정수",
        start_dt=start_dt,
        end_dt=end_dt,
    )

    monthly_exp = load_monthly_metric(
        summary_dir=summary_dir,
        prefix="만기",
        month_col_name="만기월",
        output_col_name="만기계정수",
        start_dt=start_dt,
        end_dt=end_dt,
    )

    # -------------------------------------------------
    # 병합
    # -------------------------------------------------
    monthly = monthly.merge(monthly_new, on="기준월", how="left")
    monthly = monthly.merge(monthly_term, on="기준월", how="left")
    monthly = monthly.merge(monthly_exp, on="기준월", how="left")

    for col in ["신규계정수", "해지계정수", "만기계정수"]:
        if col not in monthly.columns:
            monthly[col] = 0
        monthly[col] = pd.to_numeric(monthly[col], errors="coerce").fillna(0)

    # -------------------------------------------------
    # 천 단위 변환
    # -------------------------------------------------
    value_cols = ["신규계정수", "해지계정수", "만기계정수", "순증계정수", "누적계정수"]
    for col in value_cols:
        monthly[col] = monthly[col] / 1000

    # -------------------------------------------------
    # KPI
    # 기간 / 신규 / 해지 / 만기 / 순증 / 누적
    # -------------------------------------------------
    # ✅ 기간 포맷 변환 (YYYY.MM → YY.MM)
    start_fmt = start_month[2:]
    end_fmt = end_month[2:]

    # ✅ 시작 = 종료면 하나만 표시
    if start_fmt == end_fmt:
        period_label = f"{start_fmt}"
    else:
        period_label = f"{start_fmt} ~ {end_fmt}"


    sum_new = monthly["신규계정수"].sum()
    sum_term = monthly["해지계정수"].sum()
    sum_exp = monthly["만기계정수"].sum()
    sum_net = monthly["순증계정수"].sum()
    last_cum = monthly["누적계정수"].iloc[-1]

    c1, c2, c3, c4, c5, c6 = st.columns(6)

    c1.metric("📅 기간", period_label)
    c2.metric("➕ 신규", f"{sum_new:,.0f}")
    c3.metric("➖ 해지", f"{sum_term:,.0f}")
    c4.metric("⏳ 만기", f"{sum_exp:,.0f}")

    net_color = "red" if sum_net < 0 else "black"
    arrow = "▼" if sum_net < 0 else "▲"

    c5.metric(
        "📈 순증",
        f"{arrow} {sum_net:,.0f}"
    )


    c6.metric("📊 누적", f"{last_cum:,.0f}")

    st.caption("단위 : 천계정")

    # -------------------------------------------------
    # 그래프용 컬럼
    # -------------------------------------------------
    monthly["기준월표시"] = monthly["기준월"].dt.strftime("%y.%m")
    monthly["연도"] = monthly["기준월"].dt.year

    x = range(len(monthly))

    # ✅ 연도 경계 계산
    year_boundaries = []
    prev_year = None
    for i, y in enumerate(monthly["연도"]):
        if prev_year is not None and y != prev_year:
            year_boundaries.append(i - 0.5)
        prev_year = y


    # -------------------------------------------------
    # ✅ 1. 순증 그래프 (위)
    # -------------------------------------------------
    st.markdown("### 📈 순증 추이")

    fig1, ax1 = plt.subplots(figsize=(14, 2.6))

    ax1.plot(
        x,
        monthly["순증계정수"],
        color="#C0504D",
        marker="o",
        linewidth=2
    )

    ax1.axhline(0, linestyle="--", color="gray")

    # ✅ 순증 값 표시 (오른쪽 + 위/아래 분리)
    for i, v in enumerate(monthly["순증계정수"]):
        offset = 1.5 if v >= 0 else -1.5
        ax1.text(
            i + 0.15,
            v + offset,
            f"{v:,.0f}",
            ha="left",
            va="bottom" if v >= 0 else "top",
            fontsize=10
        )

    # ✅ 연도 경계선
    for b in year_boundaries:
        ax1.axvline(x=b, linestyle="--", color="lightgray", alpha=0.7)

    ax1.set_ylim(
        monthly["순증계정수"].min() - 20,
        monthly["순증계정수"].max() + 20
    )

    ax1.set_xticks(list(x))
    ax1.set_xticklabels(monthly["기준월표시"])

    st.pyplot(fig1)


    # -------------------------------------------------
    # ✅ 2. 누적 그래프 (아래)
    # -------------------------------------------------
    st.markdown("### 📊 누적 계정")

    fig2, ax2 = plt.subplots(figsize=(14, 3.2))

    ax2.bar(
        x,
        monthly["누적계정수"],
        color="#4F81BD",
        alpha=0.9
    )

    # ✅ 누적 값 표시
    for i, v in enumerate(monthly["누적계정수"]):
        ax2.text(
            i,
            v,
            f"{v:,.0f}",
            ha="center",
            va="bottom",
            fontsize=10
        )

    # ✅ 연도 경계선
    for b in year_boundaries:
        ax2.axvline(x=b, linestyle="--", color="lightgray", alpha=0.7)

    ax2.set_ylim(
        monthly["누적계정수"].min() - 100,
        monthly["누적계정수"].max() + 100
    )

    ax2.set_xticks(list(x))
    ax2.set_xticklabels(monthly["기준월표시"], rotation=45)

    st.pyplot(fig2)


    # -------------------------------------------------
    # Pivot
    # 월별 + 연도별 누적
    # 신규 / 해지 / 만기 / 순증 = 연도 합계
    # 누적 = 연말 마지막 월 값
    # -------------------------------------------------
    st.markdown("### 📋 Pivot 형태")

    table_df = monthly.copy()

    pivot_raw = build_pivot_with_yearly_cumulative(table_df)
    pivot_display = pivot_raw.astype(object).copy()

    for col in pivot_display.columns:
        for row_name in pivot_display.index:
            pivot_display.loc[row_name, col] = f"{pivot_raw.loc[row_name, col]:,.0f}"

    year_cum_cols = [c for c in pivot_display.columns if "년 누적" in c]

    def style_rows(row):
        styles = []
        for col_name, value in row.items():
            style = ""

            # 연도 누적 칼럼 배경 강조
            if col_name in year_cum_cols:
                style += "background-color: #F3F6FA; font-weight: bold;"

            # 순증 음수 빨간색
            if row.name == "순증계정수" and str(value).startswith("-"):
                style += "color: red;"

            styles.append(style)
        return styles

    styled_df = pivot_display.style.apply(style_rows, axis=1)

    # ✅ 글자 크기 10% 확대
    styled_df = styled_df.set_table_styles([
        {"selector": "th", "props": [("font-size", "110%")]},
        {"selector": "td", "props": [("font-size", "110%")]}
    ])

    st.dataframe(
        styled_df,
        width="stretch"
    )