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


def extract_month_from_filename(file_name: str):
    """
    파일명에서 yyyy.mm / yyyy-mm / yyyymm 추출
    """
    stem = Path(file_name).stem
    m = re.search(r"(20\d{2})[.\-_]?(\d{2})", stem)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    return None


def detect_value_col(df: pd.DataFrame) -> str:
    candidates = ["계정수", "신규계정수", "해지계정수", "만기계정수"]
    for c in candidates:
        if c in df.columns:
            return c
    raise ValueError(f"계정수 컬럼을 찾을 수 없습니다. 현재 컬럼: {list(df.columns)}")


def normalize_contract_type(series: pd.Series) -> pd.Series:
    """
    계약유형분류 정리
    - 일반판매무상 / 일반판매유상 -> 일시불
    """
    s = series.fillna("").astype(str).str.strip()

    s = s.replace({
        "일반판매무상": "일시불",
        "일반판매유상": "일시불"
    })

    return s


# ---------------------------------------------------------
# 신규 / 해지 / 만기 DB 로드 (월별, 계약유형별)
# ---------------------------------------------------------
def load_monthly_contract_metric(
    summary_dir: Path,
    prefix: str,
    month_col_name: str,
    output_col_name: str,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
) -> pd.DataFrame:
    """
    SummaryDB의 신규/해지/만기 parquet를 불러와
    기준월 + 계약유형분류 기준으로 집계

    결과:
    기준월 / 계약유형분류 / output_col_name
    """
    files = sorted(summary_dir.glob(f"{prefix}_*.parquet"))

    if not files:
        return pd.DataFrame(columns=["기준월", "계약유형분류", output_col_name])

    all_frames = []

    for fp in files:
        try:
            df = pd.read_parquet(fp)
            df = normalize_columns(df)

            if "계약유형분류" not in df.columns:
                continue

            df["계약유형분류"] = normalize_contract_type(df["계약유형분류"])

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

            grp = (
                df.groupby(["기준월", "계약유형분류"], as_index=False)[value_col]
                .sum()
                .rename(columns={value_col: output_col_name})
            )

            all_frames.append(grp)

        except Exception:
            continue

    if not all_frames:
        return pd.DataFrame(columns=["기준월", "계약유형분류", output_col_name])

    result = pd.concat(all_frames, ignore_index=True)
    result = (
        result.groupby(["기준월", "계약유형분류"], as_index=False)[output_col_name]
        .sum()
        .sort_values(["기준월", "계약유형분류"])
    )
    return result


# ---------------------------------------------------------
# 누적 / 순증 로드 (월별, 계약유형별)
# ---------------------------------------------------------
def load_monthly_cumulative_contract_metrics(
    cumulative_path: Path,
    start_dt: pd.Timestamp,
    end_dt: pd.Timestamp,
) -> pd.DataFrame:
    """
    누적_년월.parquet에서 기준월 + 계약유형분류 기준으로
    순증계정수 / 누적계정수 가져오기
    """
    if not cumulative_path.exists():
        raise FileNotFoundError(f"누적 파일이 없습니다: {cumulative_path}")

    df = pd.read_parquet(cumulative_path)
    df = normalize_columns(df)

    required_cols = ["기준월", "계약유형분류", "순증계정수", "누적계정수"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"누적 파일 필수 컬럼이 없습니다: {missing}")

    df["기준월"] = normalize_month_series(df["기준월"])
    df["계약유형분류"] = normalize_contract_type(df["계약유형분류"])

    df["순증계정수"] = pd.to_numeric(df["순증계정수"], errors="coerce").fillna(0)
    df["누적계정수"] = pd.to_numeric(df["누적계정수"], errors="coerce").fillna(0)

    df = df[(df["기준월"] >= start_dt) & (df["기준월"] <= end_dt)]

    if df.empty:
        return pd.DataFrame(columns=["기준월", "계약유형분류", "순증", "누적"])

    result = (
        df.groupby(["기준월", "계약유형분류"], as_index=False)[["순증계정수", "누적계정수"]]
        .sum()
        .rename(columns={
            "순증계정수": "순증",
            "누적계정수": "누적"
        })
        .sort_values(["기준월", "계약유형분류"])
    )

    return result


# ---------------------------------------------------------
# 월별 + 연도누적 컬럼 생성
# ---------------------------------------------------------
def build_pivot_with_yearly_cumulative(df: pd.DataFrame) -> pd.DataFrame:
    """
    입력 df 컬럼:
    기준월, 기준월표시, 신규, 해지, 만기, 순증, 누적

    출력:
    행 = 신규/해지/만기/순증/누적
    열 = 25.01, 25.02, ..., 25년 누적, 26.01, ..., 26년 누적
    """
    metric_order = ["신규", "해지", "만기", "순증", "누적"]

    temp = df.copy().sort_values("기준월")
    temp["연도"] = temp["기준월"].dt.year
    temp["기준월표시"] = temp["기준월"].dt.strftime("%y.%m")

    final = pd.DataFrame(index=metric_order)

    years = list(dict.fromkeys(temp["연도"].tolist()))  # 순서 유지

    for year in years:
        year_df = temp[temp["연도"] == year].copy()

        # 월별 컬럼 추가
        for _, row in year_df.iterrows():
            month_label = row["기준월표시"]
            final[month_label] = [row[m] for m in metric_order]

        # 연도 누적 컬럼 추가
        year_col = f"{str(year)[2:]}년 누적"
        final[year_col] = [
            year_df["신규"].sum(),
            year_df["해지"].sum(),
            year_df["만기"].sum(),
            year_df["순증"].sum(),
            year_df["누적"].iloc[-1],   # 누적은 마지막 월 값
        ]

    return final


# ---------------------------------------------------------
# 계약유형별 누적 적층 그래프
# ---------------------------------------------------------
def render_stacked_cumulative_chart(result: pd.DataFrame):
    """
    월별 누적계정을 계약유형별 적층 막대로 표시
    - 아래부터: 운용리스 → 금융리스 → 일시불 → 케어십
    - 각 segment 중앙에 수치 + 비중 표시
    - 막대 상단에 월별 총 누적 수치 표시
    """
    if result.empty:
        st.caption("그래프용 데이터 없음")
        return

    # ✅ 적층 순서 = 범례 순서
    chart_order = ["운용리스", "금융리스", "일시불", "케어십"]

    # ✅ 금융리스 색상 변경 (텍스트 가독성 확보용)
    color_map = {
        "운용리스": "#4F81BD",   # 파랑
        "금융리스": "#8FD3E8",   # 밝은 청록
        "일시불":   "#F79646",   # 주황
        "케어십":   "#C0504D",   # 빨강
    }

    monthly_pivot = (
        result.pivot_table(
            index="기준월",
            columns="계약유형분류",
            values="누적",
            aggfunc="sum"
        )
        .fillna(0)
        .sort_index()
    )

    # ✅ 누락 계약유형 컬럼 보정
    for c in chart_order:
        if c not in monthly_pivot.columns:
            monthly_pivot[c] = 0

    monthly_pivot = monthly_pivot[chart_order]
    month_labels = monthly_pivot.index.strftime("%y.%m").tolist()

    x = range(len(monthly_pivot))

    st.markdown("### 📊 계약유형별 월별 누적 계정")
    fig, ax = plt.subplots(figsize=(14, 4.2))

    bottom = pd.Series([0] * len(monthly_pivot), index=monthly_pivot.index)

    # ✅ 막대 적층
    bar_handles = []
    for ct in chart_order:
        vals = monthly_pivot[ct]

        bars = ax.bar(
            x,
            vals,
            bottom=bottom,
            label=ct,
            color=color_map.get(ct, "#999999"),
            alpha=0.9
        )
        bar_handles.append(bars)

        # ✅ 각 segment 가운데 값 + 비중 표시
        totals = monthly_pivot.sum(axis=1)

        for i, v in enumerate(vals):
            if v == 0:
                continue

            total = totals.iloc[i]
            pct = (v / total * 100) if total != 0 else 0

            y_pos = bottom.iloc[i] + (v / 2)

            ax.text(
                i,
                y_pos,
                f"{v:,.0f}\n({pct:.0f}%)",
                ha="center",
                va="center",
                fontsize=9,
                color="#1B5E20",   # ✅ 짙은 초록색
                fontweight="bold"
            )

        bottom = bottom + vals

    # ✅ 월별 총 누적 수량 표시 (상단)
    totals = monthly_pivot.sum(axis=1)
    for i, total in enumerate(totals):
        ax.text(
            i,
            total + max(totals) * 0.015,
            f"{total:,.0f}",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
            color="black"
        )

    ax.set_xticks(list(x))
    ax.set_xticklabels(month_labels, rotation=45)
    ax.set_ylabel("누적계정수 (천)")

    # ✅ 범례 순서도 적층 순서와 동일하게 고정
    handles, labels = ax.get_legend_handles_labels()
    order_map = {name: idx for idx, name in enumerate(chart_order)}
    ordered = sorted(zip(handles, labels), key=lambda x: order_map.get(x[1], 999))
    ordered_handles = [h for h, _ in ordered]
    ordered_labels = [l for _, l in ordered]

    # ✅ 범례 가로 배치 + 그래프 위쪽 바깥으로 이동
    ax.legend(
        ordered_handles,
        ordered_labels,
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),   # 그래프 위쪽
        ncol=4,                        # 가로 4개
        frameon=False                  # 테두리 제거
    )

    y_max = totals.max() * 1.15 if len(totals) else 1
    ax.set_ylim(0, y_max)

    plt.tight_layout()
    st.pyplot(fig)


# ---------------------------------------------------------
# 메인 Dashboard
# ---------------------------------------------------------
def render_dashboard(context):

    summary_dir = Path(context["summary_dir"])
    start_month = context["start_month"]
    end_month = context["end_month"]

    cumulative_path = summary_dir / "누적_년월.parquet"

    start_dt = pd.to_datetime(start_month.replace(".", "-"), errors="coerce")
    end_dt = pd.to_datetime(end_month.replace(".", "-"), errors="coerce")

    if pd.isna(start_dt) or pd.isna(end_dt):
        st.error("조회 기간 형식이 올바르지 않습니다. 예: 2025.01")
        return

    # -------------------------------------------------
    # 1. 신규 / 해지 / 만기 월별 로드
    # -------------------------------------------------
    df_new = load_monthly_contract_metric(
        summary_dir=summary_dir,
        prefix="신규",
        month_col_name="계약시작월",
        output_col_name="신규",
        start_dt=start_dt,
        end_dt=end_dt,
    )

    df_term = load_monthly_contract_metric(
        summary_dir=summary_dir,
        prefix="해지",
        month_col_name="해지완료월",
        output_col_name="해지",
        start_dt=start_dt,
        end_dt=end_dt,
    )

    df_exp = load_monthly_contract_metric(
        summary_dir=summary_dir,
        prefix="만기",
        month_col_name="만기월",
        output_col_name="만기",
        start_dt=start_dt,
        end_dt=end_dt,
    )

    # -------------------------------------------------
    # 2. 순증 / 누적 월별 로드
    # -------------------------------------------------
    try:
        df_cum = load_monthly_cumulative_contract_metrics(
            cumulative_path=cumulative_path,
            start_dt=start_dt,
            end_dt=end_dt,
        )
    except Exception as e:
        st.error(f"누적 파일 로드 중 오류: {e}")
        return

    # -------------------------------------------------
    # 3. 병합
    # -------------------------------------------------
    result = None

    for part in [df_new, df_term, df_exp, df_cum]:
        if result is None:
            result = part.copy()
        else:
            result = result.merge(part, on=["기준월", "계약유형분류"], how="outer")

    if result is None or result.empty:
        st.warning("조회 기간에 데이터가 없습니다.")
        return

    for col in ["신규", "해지", "만기", "순증", "누적"]:
        if col not in result.columns:
            result[col] = 0
        result[col] = pd.to_numeric(result[col], errors="coerce").fillna(0)

    # -------------------------------------------------
    # 4. 천 단위 변환
    # -------------------------------------------------
    result[["신규", "해지", "만기", "순증", "누적"]] = (
        result[["신규", "해지", "만기", "순증", "누적"]] / 1000
    )

    # -------------------------------------------------
    # 5. 기준월 표시용 문자열
    # -------------------------------------------------
    result["기준월표시"] = result["기준월"].dt.strftime("%y.%m")

    # -------------------------------------------------
    # 6. 그래프 출력
    # -------------------------------------------------
    render_stacked_cumulative_chart(result)

    # -------------------------------------------------
    # 7. 출력 순서 대상 계약유형
    # -------------------------------------------------
    contract_types = ["금융리스", "운용리스", "일시불", "케어십"]

    # -------------------------------------------------
    # 8. 계약유형별 표 출력 (행/열 전환 + 연도 누적)
    # -------------------------------------------------
    st.markdown("### 📋 계약유형별 누적 계정 현황")
    st.caption("단위 : 천계정")

    for contract_type in contract_types:
        sub = result[result["계약유형분류"] == contract_type].copy()

        st.markdown(f"#### {contract_type}")

        if sub.empty:
            st.caption("데이터 없음")
            continue

        sub = sub[["기준월", "기준월표시", "신규", "해지", "만기", "순증", "누적"]].copy()
        sub = sub.sort_values("기준월")

        # ✅ 월별 + 연도누적 Pivot 생성
        pivot = build_pivot_with_yearly_cumulative(sub)

        # 표시용 문자열
        display = pivot.copy().astype(object)
        for col in display.columns:
            for row in display.index:
                display.loc[row, col] = f"{pivot.loc[row, col]:,.0f}"

        year_cum_cols = [c for c in display.columns if "년 누적" in c]

        def style_rows(row):
            styles = []
            for col_name, value in row.items():
                style = ""

                # 연도 누적 컬럼 강조
                if col_name in year_cum_cols:
                    style += "background-color: #F3F6FA; font-weight: bold;"

                # 순증 음수 빨간색
                if row.name == "순증" and str(value).startswith("-"):
                    style += "color:red;"

                styles.append(style)
            return styles

        styled_df = display.style.apply(style_rows, axis=1).set_table_styles([
            {"selector": "th", "props": [("font-size", "110%")]},
            {"selector": "td", "props": [("font-size", "110%")]}
        ])

        st.dataframe(
            styled_df,
            width="stretch"
        )
