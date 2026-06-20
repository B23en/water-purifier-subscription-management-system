from pathlib import Path
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm


STATE_PREFIX = "new_channel_sales"
HYCARE_CHANNEL_NAME = "하이케어"

plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False


# =========================================================
# 유틸
# =========================================================
def _safe_read_parquet(path: Path):
    return pd.read_parquet(path)


def _month_range(start_month: str, end_month: str):
    """
    start_month, end_month: 'YYYY.MM'
    반환: PeriodIndex(M)
    """
    start_p = pd.Period(start_month.replace(".", "-"), freq="M")
    end_p = pd.Period(end_month.replace(".", "-"), freq="M")
    return pd.period_range(start=start_p, end=end_p, freq="M")


def _format_month_col(period_obj: pd.Period):
    """
    2025-01 -> '25.1월'
    """
    return f"{str(period_obj.year)[-2:]}.{period_obj.month}월"


def _format_year_total_col(year: int):
    """
    2025 -> '25년 누적'
    """
    return f"{str(year)[-2:]}년 누적"


def _format_qty_thousand(x):
    if pd.isna(x):
        return ""
    return f"{x / 1000:,.1f}"


def _format_ratio(x):
    if pd.isna(x):
        return ""
    return f"{x:.0%}"


def _normalize_resubscribe_type(value):
    """
    SummaryDB의 재구독유형 값을
    - 재구독 포함 -> 재구독
    - 나머지 -> 신규
    로 단순화
    """
    if pd.isna(value):
        return "신규"

    text = str(value).strip()
    if "재구독" in text:
        return "재구독"
    return "신규"


def _display_resubscribe_label(label: str):
    if label == "전체":
        return "전체"
    if label == "신규":
        return "└ 신규"
    if label == "재구독":
        return "└ 재구독"
    return label


def _year_state_key(year: int):
    return f"{STATE_PREFIX}_expand_year_{year}"


def _range_state_key(start_month: str, end_month: str):
    return f"{STATE_PREFIX}_range::{start_month}~{end_month}"


# =========================================================
# 데이터 로드
# =========================================================
def _load_and_prepare(summary_dir: Path, start_month: str, end_month: str):
    file_path = summary_dir / "신규_년월.parquet"

    if not file_path.exists():
        raise FileNotFoundError(f"요약 DB 파일이 없습니다: {file_path}")

    df = _safe_read_parquet(file_path)

    required_cols = ["계약시작월", "채널분류", "계약유형분류", "재구독유형", "계정수"]
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        raise ValueError(f"필수 컬럼이 없습니다: {missing_cols}")

    work = df.copy()

    work["계약시작월"] = work["계약시작월"].astype(str).str.strip()
    work["채널분류"] = work["채널분류"].fillna("미분류").astype(str)
    work["계약유형분류"] = work["계약유형분류"].fillna("").astype(str)
    work["재구독유형"] = work["재구독유형"].fillna("").astype(str)
    work["계정수"] = pd.to_numeric(work["계정수"], errors="coerce").fillna(0)

    # 케어십 제외
    work = work[work["계약유형분류"] != "케어십"].copy()

    # YYYY.MM -> Period(M)
    work["월Period"] = pd.to_datetime(
        work["계약시작월"],
        format="%Y.%m",
        errors="coerce"
    ).dt.to_period("M")

    work = work[work["월Period"].notna()].copy()

    start_p = pd.Period(start_month.replace(".", "-"), freq="M")
    end_p = pd.Period(end_month.replace(".", "-"), freq="M")

    work = work[
        (work["월Period"] >= start_p) &
        (work["월Period"] <= end_p)
    ].copy()

    if work.empty:
        return work

    work["재구독유형표시"] = work["재구독유형"].apply(_normalize_resubscribe_type)

    return work


# =========================================================
# 그래프 데이터
# =========================================================
def _build_channel_graph_table(work: pd.DataFrame, start_month: str, end_month: str):
    """
    그래프용 채널 전체 월별 판매수량
    - 연도 누적 제외
    - 하이케어 신규/재구독 상세는 표에서만 제공
    """
    if work.empty:
        return pd.DataFrame()

    months = _month_range(start_month, end_month)

    overall = (
        work.groupby(["채널분류", "월Period"], dropna=False)["계정수"]
        .sum()
        .unstack(fill_value=0)
        .reindex(columns=months, fill_value=0)
    )

    # 판매수량 기준 내림차순
    channel_totals = overall.sum(axis=1).sort_values(ascending=False)
    graph_df = overall.loc[channel_totals.index]

    # 천 단위 변환
    graph_df = graph_df / 1000

    return graph_df


def _render_channel_line_chart(work: pd.DataFrame, start_month: str, end_month: str):
    graph_df = _build_channel_graph_table(work, start_month, end_month)

    if graph_df.empty:
        st.caption("그래프용 데이터가 없습니다.")
        return

    months = list(graph_df.columns)
    x = range(len(months))
    month_labels = [f"{str(m.year)[-2:]}.{m.month}" for m in months]

    st.markdown("### 채널별 월별 판매수량 추이")
    st.caption("※ 그래프는 채널 전체 기준 / 하이케어 신규·재구독 상세는 표에서만 제공")

    fig, ax = plt.subplots(figsize=(14, 4.5))

    cmap = plt.get_cmap("tab20")
    colors = [cmap(i % 20) for i in range(len(graph_df.index))]

    for idx, channel in enumerate(graph_df.index):
        y = graph_df.loc[channel].values

        ax.plot(
            x,
            y,
            marker="o",
            linewidth=2,
            label=channel,
            color=colors[idx]
        )

        # 점 수치 표시
        for i, v in enumerate(y):
            if pd.isna(v):
                continue

            offset = max(graph_df.max().max() * 0.01, 0.05)

            ax.text(
                i,
                v + offset,
                f"{v:,.1f}",
                ha="center",
                va="bottom",
                fontsize=9
            )

    # 연도 경계선 (연도 누적 컬럼은 그래프에 없고, 월 사이 구분선만 추가)
    prev_year = None
    for i, m in enumerate(months):
        if prev_year is not None and m.year != prev_year:
            ax.axvline(i - 0.5, color="lightgray", linestyle="--", linewidth=1)
        prev_year = m.year

    ax.set_xticks(list(x))
    ax.set_xticklabels(month_labels, rotation=45)
    ax.set_ylabel("판매수량(천)")
    ax.set_title("채널별 월별 판매수량")

    # 범례
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=min(5, len(graph_df.index)),
        frameon=False
    )

    plt.tight_layout(rect=[0, 0, 1, 0.92])
    st.pyplot(fig)


# =========================================================
# 연도별 접기/펼치기 상태
# =========================================================
def _init_year_expand_state(start_month: str, end_month: str):
    months = _month_range(start_month, end_month)
    years = sorted(set([p.year for p in months]))
    end_year = pd.Period(end_month.replace(".", "-"), freq="M").year
    current_range_key = _range_state_key(start_month, end_month)

    if st.session_state.get(f"{STATE_PREFIX}_initialized_range") != current_range_key:
        for year in years:
            # 종료연도 + 직전연도는 펼침, 그 이전은 접힘
            st.session_state[_year_state_key(year)] = (year >= end_year - 1)

        st.session_state[f"{STATE_PREFIX}_initialized_range"] = current_range_key


def _get_visible_columns_and_button_positions(start_month: str, end_month: str):
    months = _month_range(start_month, end_month)
    years = sorted(set([p.year for p in months]))

    visible_cols = ["채널", "재구독유형", "항목"]
    button_specs = []

    for year in years:
        expanded = st.session_state.get(_year_state_key(year), False)
        year_months = [p for p in months if p.year == year]

        if expanded:
            for m in year_months:
                visible_cols.append(_format_month_col(m))

        visible_cols.append(_format_year_total_col(year))

        button_specs.append({
            "year": year,
            "col_index": len(visible_cols) - 1,
            "expanded": expanded
        })

    return visible_cols, button_specs


def _render_year_toggle_row(visible_cols, button_specs):
    """
    연도 누적 컬럼 바로 위에 + / - 버튼 배치
    """
    if not visible_cols:
        return

    ctrl_cols = st.columns(len(visible_cols), gap="small")
    button_map = {spec["col_index"]: spec for spec in button_specs}

    for idx in range(len(visible_cols)):
        with ctrl_cols[idx]:
            spec = button_map.get(idx)

            if spec is None:
                st.markdown("<div style='height: 38px;'></div>", unsafe_allow_html=True)
                continue

            year = spec["year"]
            expanded = spec["expanded"]
            label = "−" if expanded else "+"
            help_text = f"{year}년 월별 데이터 {'숨기기' if expanded else '보기'}"

            if st.button(
                label,
                key=f"{STATE_PREFIX}_toggle_year_btn_{year}",
                help=help_text,
                use_container_width=True
            ):
                st.session_state[_year_state_key(year)] = not expanded
                st.rerun()


# =========================================================
# Matrix Table 생성
# =========================================================
def _build_matrix_table(work: pd.DataFrame, start_month: str, end_month: str):
    """
    하이케어만 전체/신규/재구독 상세 표시
    나머지 채널은 전체만 표시
    """
    if work.empty:
        return pd.DataFrame()

    months = _month_range(start_month, end_month)

    # ---------------------------------------------
    # 피벗 소스 생성
    # - 전체: 모든 채널
    # - 상세: 하이케어만 신규/재구독
    # ---------------------------------------------
    overall = work.copy()
    overall["재구독유형계층"] = "전체"

    detail_hycare = work[work["채널분류"] == HYCARE_CHANNEL_NAME].copy()
    detail_hycare["재구독유형계층"] = detail_hycare["재구독유형표시"]

    pivot_source = pd.concat([overall, detail_hycare], ignore_index=True)

    qty_pivot = (
        pivot_source.groupby(["채널분류", "재구독유형계층", "월Period"], dropna=False)["계정수"]
        .sum()
        .unstack(fill_value=0)
    )

    qty_pivot = qty_pivot.reindex(columns=months, fill_value=0)

    # 채널 정렬: 전체 판매수량 기준 내림차순
    channel_totals = {}
    for channel in qty_pivot.index.get_level_values(0).unique():
        if (channel, "전체") in qty_pivot.index:
            channel_totals[channel] = qty_pivot.loc[(channel, "전체")].sum()
        else:
            channel_totals[channel] = 0

    channel_order = sorted(channel_totals.keys(), key=lambda x: channel_totals[x], reverse=True)

    # 전체 시장 합계 (전체 비중 모수)
    market_total = (
        overall.groupby("월Period", dropna=False)["계정수"]
        .sum()
        .reindex(months, fill_value=0)
    )

    # 표시 컬럼 정의
    display_col_defs = []
    years = sorted(set([p.year for p in months]))
    for year in years:
        year_months = [p for p in months if p.year == year]
        for m in year_months:
            display_col_defs.append(("month", m))
        display_col_defs.append(("year_total", year))

    rows = []

    for channel in channel_order:
        # 하이케어만 상세행 포함
        if channel == HYCARE_CHANNEL_NAME:
            visible_tiers = ["전체", "신규", "재구독"]
        else:
            visible_tiers = ["전체"]

        if (channel, "전체") in qty_pivot.index:
            channel_total_series = qty_pivot.loc[(channel, "전체")]
        else:
            channel_total_series = pd.Series(0, index=months)

        first_channel_row = True

        for tier in visible_tiers:
            if (channel, tier) in qty_pivot.index:
                qty_series = qty_pivot.loc[(channel, tier)]
            else:
                qty_series = pd.Series(0, index=months)

            display_channel_text = channel if first_channel_row else ""
            first_channel_row = False

            tier_label = _display_resubscribe_label(tier)

            row_qty = {
                "채널": display_channel_text,
                "재구독유형": tier_label,
                "항목": "판매수량"
            }
            row_ratio = {
                "채널": "",
                "재구독유형": tier_label,
                "항목": "판매비중"
            }

            for col_type, value in display_col_defs:
                if col_type == "month":
                    month_val = qty_series.get(value, 0)
                    col_name = _format_month_col(value)
                    row_qty[col_name] = _format_qty_thousand(month_val)

                    # 비중 계산
                    if tier == "전체":
                        denom = market_total.get(value, 0)
                    else:
                        denom = channel_total_series.get(value, 0)

                    row_ratio[col_name] = _format_ratio(month_val / denom) if denom != 0 else "0%"
                elif col_type == "year_total":
                    year = value
                    target_months = [p for p in months if p.year == year]
                    col_name = _format_year_total_col(year)

                    ch_year_sum = qty_series[target_months].sum() if target_months else 0
                    row_qty[col_name] = _format_qty_thousand(ch_year_sum)

                    if tier == "전체":
                        denom = market_total[target_months].sum() if target_months else 0
                    else:
                        denom = channel_total_series[target_months].sum() if target_months else 0

                    row_ratio[col_name] = _format_ratio(ch_year_sum / denom) if denom != 0 else "0%"

            rows.append(row_qty)
            rows.append(row_ratio)

    # ---------------------------------------------
    # 합계 행
    # ---------------------------------------------
    total_row = {
        "채널": "합계",
        "재구독유형": "",
        "항목": "판매수량"
    }

    for col_type, value in display_col_defs:
        if col_type == "month":
            total_row[_format_month_col(value)] = _format_qty_thousand(market_total.get(value, 0))
        elif col_type == "year_total":
            year = value
            target_months = [p for p in months if p.year == year]
            total_row[_format_year_total_col(year)] = _format_qty_thousand(
                market_total[target_months].sum() if target_months else 0
            )

    rows.append(total_row)

    result_df = pd.DataFrame(rows)

    ordered_cols = ["채널", "재구독유형", "항목"]
    for col_type, value in display_col_defs:
        if col_type == "month":
            ordered_cols.append(_format_month_col(value))
        elif col_type == "year_total":
            ordered_cols.append(_format_year_total_col(value))

    result_df = result_df[ordered_cols]

    return result_df


# =========================================================
# 스타일
# =========================================================
def _style_table(df: pd.DataFrame):
    year_total_cols = [c for c in df.columns if c.endswith("년 누적")]
    left_cols = [c for c in ["채널", "재구독유형", "항목"] if c in df.columns]

    def style_rows(row):
        styles = [""] * len(row)

        # 판매비중 행: 초록색
        if row.get("항목") == "판매비중":
            styles = ["color: #0a7a0a;" for _ in row]

        # 합계 행
        if row.get("채널") == "합계":
            styles = ["font-weight: bold; background-color: #f2f2f2;" for _ in row]

        return styles

    styler = df.style.apply(style_rows, axis=1)

    # 연도 누적 컬럼 음영
    if year_total_cols:
        styler = styler.set_properties(
            subset=year_total_cols,
            **{
                "background-color": "#fff4cc",
                "font-weight": "bold"
            }
        )

    # 왼쪽 컬럼 강조
    if left_cols:
        styler = styler.set_properties(
            subset=left_cols,
            **{"font-weight": "bold"}
        )

    # 하이케어 상세행(신규/재구독) 재구독유형 표시 약간 연하게
    child_rows = df.index[df["재구독유형"].astype(str).str.startswith("└")]
    if len(child_rows) > 0 and "재구독유형" in df.columns:
        styler = styler.set_properties(
            subset=pd.IndexSlice[child_rows, ["재구독유형"]],
            **{"color": "#4a4a4a"}
        )

    return styler


# =========================================================
# Main Renderer
# =========================================================
def render_dashboard(context: dict):
    summary_dir = Path(context["summary_dir"])
    start_month = context["start_month"]   # ex) '2025.01'
    end_month = context["end_month"]       # ex) '2026.05'

    st.markdown("## 월별 워터케어 채널별 판매수량")
    st.caption("※ 계약유형분류 '케어십' 제외 / 판매수량은 천 단위 / 판매비중은 월별 및 연도누적 기준")

    try:
        work = _load_and_prepare(summary_dir, start_month, end_month)
    except Exception as e:
        st.error(str(e))
        return

    if work.empty:
        st.warning("선택한 기간에 해당하는 데이터가 없습니다.")
        return

    # ✅ 그래프 추가
    _render_channel_line_chart(work, start_month, end_month)

    # 연도 상태 초기화
    _init_year_expand_state(start_month, end_month)

    # 전체 테이블 생성
    full_df = _build_matrix_table(work, start_month, end_month)

    if full_df.empty:
        st.warning("표시할 데이터가 없습니다.")
        return

    # 현재 상태 기준 표시 컬럼 계산
    visible_cols, button_specs = _get_visible_columns_and_button_positions(start_month, end_month)
    visible_cols = [c for c in visible_cols if c in full_df.columns]
    display_df = full_df[visible_cols].copy()

    st.markdown("### 채널별 판매수량 / 판매비중")

    # 연도 토글 버튼
    _render_year_toggle_row(visible_cols, button_specs)

    # 데이터 테이블
    st.dataframe(
        _style_table(display_df),
        use_container_width=True,
        hide_index=True,
        height=760
    )