from pathlib import Path
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np 


STATE_PREFIX_BASE = "contract_type_grouped_sales"

PARENT_ORDER = ["렌탈", "일시불", "케어십"]

DETAIL_MAP = {
    "렌탈": ["금융리스", "운용리스"],
    "일시불": ["일반판매무상", "일반판매유상"],
    "케어십": ["케어십"],
}

DETAIL_ORDER = ["금융리스", "운용리스", "일반판매무상", "일반판매유상", "케어십"]

CONTRACT_TYPE_PARENT_MAP = {
    "금융리스": "렌탈",
    "운용리스": "렌탈",
    "일반판매무상": "일시불",
    "일반판매유상": "일시불",
    "케어십": "케어십",
}

DATA_TYPE_CONFIG = {
    "신규": {
        "file_name": "신규_년월.parquet",
        "month_col": "계약시작월",
        "title": "계약유형별 판매수량(한국)",
        "section_title": "계약유형별 판매수량 / 판매비중",
        "graph_title": "계약유형별 월별 판매수량 추이",
    },
    "해지": {
        "file_name": "해지_년월.parquet",
        "month_col": "해지완료월",
        "title": "계약유형별 해지수량(한국)",
        "section_title": "계약유형별 해지수량 / 비중",
        "graph_title": "계약유형별 월별 해지수량 추이",
    },
    "만기": {
        "file_name": "만기_년월.parquet",
        "month_col": "만기월",
        "title": "계약유형별 만기수량(한국)",
        "section_title": "계약유형별 만기수량 / 비중",
        "graph_title": "계약유형별 월별 만기수량 추이",
    },
}

COLOR_MAP = {
    "금융리스": "#4F81BD",
    "운용리스": "#C0504D",
    "일반판매무상": "#9BBB59",
    "일반판매유상": "#F79646",
    "케어십": "#8064A2",
}


# =========================================================
# 유틸
# =========================================================
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False


def _safe_read_parquet(path: Path):
    return pd.read_parquet(path)


def _month_range(start_month: str, end_month: str):
    start_p = pd.Period(start_month.replace(".", "-"), freq="M")
    end_p = pd.Period(end_month.replace(".", "-"), freq="M")
    return pd.period_range(start=start_p, end=end_p, freq="M")


def _format_month_col(period_obj: pd.Period):
    return f"{str(period_obj.year)[-2:]}.{period_obj.month}월"


def _format_year_total_col(year: int):
    return f"{str(year)[-2:]}년 누적"


def _format_qty_thousand(x):
    if pd.isna(x):
        return ""
    return f"{x / 1000:,.1f}"


def _format_ratio(x):
    if pd.isna(x):
        return ""
    return f"{x:.0%}"


def _parent_of_contract_type(value):
    if pd.isna(value):
        return "기타"

    text = str(value).strip()
    return CONTRACT_TYPE_PARENT_MAP.get(text, "기타")


def _state_prefix(data_type: str):
    return f"{STATE_PREFIX_BASE}_{data_type}"


def _year_state_key(data_type: str, year: int):
    return f"{_state_prefix(data_type)}_expand_year_{year}"


def _range_state_key(data_type: str, start_month: str, end_month: str):
    return f"{_state_prefix(data_type)}_range::{start_month}~{end_month}"


def _init_state_key(data_type: str):
    return f"{_state_prefix(data_type)}_init_key"


# =========================================================
# 데이터 로드
# =========================================================
def _load_and_prepare(summary_dir: Path, start_month: str, end_month: str, data_type: str):
    config = DATA_TYPE_CONFIG[data_type]
    file_path = summary_dir / config["file_name"]
    month_col = config["month_col"]

    if not file_path.exists():
        raise FileNotFoundError(f"요약 DB 파일이 없습니다: {file_path}")

    df = _safe_read_parquet(file_path)

    required_cols = [month_col, "계약유형분류", "계정수"]
    missing_cols = [c for c in required_cols if c not in df.columns]
    if missing_cols:
        raise ValueError(f"필수 컬럼이 없습니다: {missing_cols}")

    work = df.copy()

    work[month_col] = work[month_col].astype(str).str.strip()
    work["계약유형분류"] = work["계약유형분류"].fillna("").astype(str)
    work["계정수"] = pd.to_numeric(work["계정수"], errors="coerce").fillna(0)

    work["월Period"] = pd.to_datetime(
        work[month_col],
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

    work["상위구분"] = work["계약유형분류"].apply(_parent_of_contract_type)
    work = work[work["상위구분"].isin(PARENT_ORDER)].copy()

    return work


# =========================================================
# 연도 상태
# =========================================================
def _init_year_expand_state(start_month: str, end_month: str, data_type: str):
    months = _month_range(start_month, end_month)
    years = sorted(set(m.year for m in months))
    end_year = pd.Period(end_month.replace(".", "-"), freq="M").year

    key = _range_state_key(data_type, start_month, end_month)

    if st.session_state.get(_init_state_key(data_type)) != key:
        for y in years:
            st.session_state[_year_state_key(data_type, y)] = (y >= end_year - 1)

        st.session_state[_init_state_key(data_type)] = key


def _get_visible_columns_and_button_positions(start_month: str, end_month: str, data_type: str):
    months = _month_range(start_month, end_month)
    years = sorted(set(m.year for m in months))

    visible_cols = ["구분", "세부유형", "항목"]
    button_specs = []

    idx = 3

    for y in years:
        expanded = st.session_state.get(_year_state_key(data_type, y), False)
        year_months = [m for m in months if m.year == y]

        if expanded:
            for m in year_months:
                visible_cols.append(_format_month_col(m))
                idx += 1

        visible_cols.append(_format_year_total_col(y))
        button_specs.append({
            "year": y,
            "col_index": idx,
            "expanded": expanded
        })
        idx += 1

    return visible_cols, button_specs


def _render_year_toggle_row(visible_cols, button_specs, data_type: str):
    if not visible_cols:
        return

    cols = st.columns(len(visible_cols), gap="small")
    btn_map = {s["col_index"]: s for s in button_specs}

    for i in range(len(visible_cols)):
        with cols[i]:
            spec = btn_map.get(i)

            if spec is None:
                st.markdown("<div style='height:38px'></div>", unsafe_allow_html=True)
                continue

            y = spec["year"]
            expanded = spec["expanded"]

            if st.button(
                "−" if expanded else "+",
                key=f"{_state_prefix(data_type)}_year_btn_{y}",
                help=f"{y}년 월별 데이터 {'숨기기' if expanded else '보기'}",
                width="stretch"
            ):
                st.session_state[_year_state_key(data_type, y)] = not expanded
                st.rerun()


# =========================================================
# 그래프 데이터
# =========================================================
def _build_graph_table(work: pd.DataFrame, start_month: str, end_month: str):
    """
    그래프용 월별 계약유형 상세 데이터
    연도 누적 제외
    """
    if work.empty:
        return pd.DataFrame()

    months = _month_range(start_month, end_month)

    detail_total = (
        work.groupby(["계약유형분류", "월Period"])["계정수"]
        .sum()
        .unstack(fill_value=0)
        .reindex(columns=months, fill_value=0)
    )

    graph_df = detail_total.copy()

    # 순서 고정
    idx = [x for x in DETAIL_ORDER if x in graph_df.index]
    graph_df = graph_df.reindex(idx)

    # 천 단위 변환
    graph_df = graph_df / 1000

    return graph_df


def _render_contract_type_line_chart(work: pd.DataFrame, start_month: str, end_month: str, data_type: str):
    graph_df = _build_graph_table(work, start_month, end_month)

    if graph_df.empty:
        st.caption("그래프용 데이터가 없습니다.")
        return

    config = DATA_TYPE_CONFIG[data_type]

    months = list(graph_df.columns)
    x = range(len(months))
    month_labels = [f"{str(m.year)[-2:]}.{m.month}" for m in months]

    st.markdown(f"### {config['graph_title']}")

    fig, ax = plt.subplots(figsize=(14, 4.2))

    for contract_type in graph_df.index:
        y = graph_df.loc[contract_type].values

        ax.plot(
            x,
            y,
            marker="o",
            linewidth=2,
            label=contract_type,
            color=COLOR_MAP.get(contract_type, None)
        )



    # ✅ ✅ 추세선 (각 계약유형별 안전 계산)
    y_series = pd.Series(y).astype(float)

    # ✅ NaN 제거
    valid_idx = y_series.notna()
    valid_x = np.array(list(x))[valid_idx]
    valid_y = y_series[valid_idx].values

    # ✅ 값이 2개 이상 있을 때만 추세선
    if len(valid_x) >= 2:

        # ✅ 값이 모두 동일한 경우 → 직선으로 처리
        if np.all(valid_y == valid_y[0]):
            trend_y = np.full(len(x), valid_y[0])
        else:
            z = np.polyfit(valid_x, valid_y, 1)
            trend_fn = np.poly1d(z)
            trend_y = trend_fn(x)

        ax.plot(
            x,
            trend_y,
            linestyle="--",
            linewidth=1.5,
            color="lightgray",
            alpha=0.8
        )



        # 수치 표시
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

    # 연도 경계선 추가 (그래프는 월별만, 누적 제외)
    prev_year = None
    for i, m in enumerate(months):
        if prev_year is not None and m.year != prev_year:
            ax.axvline(i - 0.5, color="lightgray", linestyle="--", linewidth=1)
        prev_year = m.year

    ax.set_xticks(list(x))
    ax.set_xticklabels(month_labels, rotation=45)
    ax.set_ylabel("수량(천)")
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=max(1, len(graph_df.index)),
        frameon=False
    )

    plt.tight_layout(rect=[0, 0, 1, 0.92])
    st.pyplot(fig)


# =========================================================
# Matrix 생성
# =========================================================
def _build_matrix_table(work: pd.DataFrame, start_month: str, end_month: str):
    if work.empty:
        return pd.DataFrame()

    months = _month_range(start_month, end_month)
    years = sorted(set(m.year for m in months))

    market_total = (
        work.groupby("월Period")["계정수"]
        .sum()
        .reindex(months, fill_value=0)
    )

    parent_total = (
        work.groupby(["상위구분", "월Period"])["계정수"]
        .sum()
        .unstack(fill_value=0)
        .reindex(columns=months, fill_value=0)
    )

    detail_total = (
        work.groupby(["상위구분", "계약유형분류", "월Period"])["계정수"]
        .sum()
        .unstack(fill_value=0)
        .reindex(columns=months, fill_value=0)
    )

    def year_sum(series, year):
        target = [m for m in months if m.year == year]
        return series[target].sum()

    display_col_defs = []
    for y in years:
        for m in months:
            if m.year == y:
                display_col_defs.append(("m", m))
        display_col_defs.append(("y", y))

    rows = []

    for parent in PARENT_ORDER:
        if parent not in parent_total.index:
            continue

        parent_series = parent_total.loc[parent]

        row_qty = {
            "구분": parent,
            "세부유형": f"{parent} *",
            "항목": "수량"
        }

        row_ratio = {
            "구분": "",
            "세부유형": f"{parent} *",
            "항목": "(%)"
        }

        for t, v in display_col_defs:
            if t == "m":
                col = _format_month_col(v)
                val = parent_series[v]
                total = market_total[v]

                row_qty[col] = _format_qty_thousand(val)
                row_ratio[col] = _format_ratio(val / total) if total else "0%"
            else:
                col = _format_year_total_col(v)
                val = year_sum(parent_series, v)
                total = year_sum(market_total, v)

                row_qty[col] = _format_qty_thousand(val)
                row_ratio[col] = _format_ratio(val / total) if total else "0%"

        rows.append(row_qty)
        rows.append(row_ratio)

        for detail in DETAIL_MAP[parent]:
            if (parent, detail) not in detail_total.index:
                continue

            detail_series = detail_total.loc[(parent, detail)]

            row_qty = {
                "구분": "",
                "세부유형": f"└ {detail}",
                "항목": "수량"
            }
            row_ratio = {
                "구분": "",
                "세부유형": f"└ {detail}",
                "항목": "(%)"
            }

            for t, v in display_col_defs:
                if t == "m":
                    col = _format_month_col(v)
                    val = detail_series[v]
                    denom = parent_series[v]

                    row_qty[col] = _format_qty_thousand(val)
                    row_ratio[col] = _format_ratio(val / denom) if denom else "0%"
                else:
                    col = _format_year_total_col(v)
                    val = year_sum(detail_series, v)
                    denom = year_sum(parent_series, v)

                    row_qty[col] = _format_qty_thousand(val)
                    row_ratio[col] = _format_ratio(val / denom) if denom else "0%"

            rows.append(row_qty)
            rows.append(row_ratio)

    total_row = {
        "구분": "합계",
        "세부유형": "",
        "항목": "수량"
    }

    for t, v in display_col_defs:
        if t == "m":
            total_row[_format_month_col(v)] = _format_qty_thousand(market_total[v])
        else:
            total_row[_format_year_total_col(v)] = _format_qty_thousand(year_sum(market_total, v))

    rows.append(total_row)

    df_result = pd.DataFrame(rows)

    ordered_cols = ["구분", "세부유형", "항목"]
    for t, v in display_col_defs:
        if t == "m":
            ordered_cols.append(_format_month_col(v))
        else:
            ordered_cols.append(_format_year_total_col(v))

    return df_result[ordered_cols]


# =========================================================
# 스타일
# =========================================================
def _style_table(df: pd.DataFrame):
    year_cols = [c for c in df.columns if c.endswith("년 누적")]
    left_cols = ["구분", "세부유형", "항목"]

    def style_row(row):
        styles = [""] * len(row)

        if row.get("항목") == "(%)":
            styles = ["color:#0a7a0a;" for _ in row]

        if row.get("구분") in PARENT_ORDER and row.get("항목") == "수량":
            styles = ["font-weight:bold;" for _ in row]

        if row.get("구분") == "합계":
            styles = ["font-weight:bold;background-color:#f2f2f2;" for _ in row]

        return styles

    styler = df.style.apply(style_row, axis=1)

    if year_cols:
        styler = styler.set_properties(
            subset=year_cols,
            **{"background-color": "#fff4cc", "font-weight": "bold"}
        )

    styler = styler.set_properties(
        subset=left_cols,
        **{"font-weight": "bold"}
    )

    child_rows = df.index[df["세부유형"].astype(str).str.startswith("└")]
    if len(child_rows) > 0:
        styler = styler.set_properties(
            subset=pd.IndexSlice[child_rows, ["세부유형"]],
            **{"color": "#4a4a4a"}
        )

    return styler


# =========================================================
# Public Renderer
# =========================================================
def render_contract_type_grouped_dashboard(context, data_type: str):
    summary_dir = Path(context["summary_dir"])
    start_month = context["start_month"]
    end_month = context["end_month"]

    config = DATA_TYPE_CONFIG[data_type]

    st.markdown(f"## {config['title']}")
    st.caption("※ 계약유형분류를 렌탈 / 일시불 / 케어십으로 재그룹핑")
    st.caption("※ 수량은 천 단위 / 판매비중은 월별 및 연도누적 기준")

    try:
        work = _load_and_prepare(summary_dir, start_month, end_month, data_type)
    except Exception as e:
        st.error(str(e))
        return

    if work.empty:
        st.warning("선택한 기간에 해당하는 데이터가 없습니다.")
        return

    # ✅ 그래프 추가
    _render_contract_type_line_chart(work, start_month, end_month, data_type)

    _init_year_expand_state(start_month, end_month, data_type)

    full_df = _build_matrix_table(work, start_month, end_month)

    if full_df.empty:
        st.warning("표시할 데이터가 없습니다.")
        return

    visible_cols, button_specs = _get_visible_columns_and_button_positions(
        start_month, end_month, data_type
    )
    visible_cols = [c for c in visible_cols if c in full_df.columns]
    display_df = full_df[visible_cols].copy()

    st.markdown(f"### {config['section_title']}")

    _render_year_toggle_row(visible_cols, button_specs, data_type)

    st.dataframe(
        _style_table(display_df),
        width="stretch",
        hide_index=True,
        height=760
    )