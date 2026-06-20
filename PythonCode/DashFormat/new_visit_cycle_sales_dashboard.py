from pathlib import Path
import pandas as pd
import streamlit as st


STATE_PREFIX = "new_visit_cycle_sales"


# =========================================================
# 유틸
# =========================================================
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


def _normalize_resubscribe_type(value):
    if pd.isna(value):
        return "신규"
    return "재구독" if "재구독" in str(value) else "신규"


def _classify_visit_type(value):
    if pd.isna(value):
        return "방문"
    return "자가" if str(value) == "자가관리" else "방문"


def _year_state_key(year: int):
    return f"{STATE_PREFIX}_expand_year_{year}"


def _range_state_key(start_month: str, end_month: str):
    return f"{STATE_PREFIX}_range::{start_month}~{end_month}"


# =========================================================
# 데이터 로드
# =========================================================
def _load(summary_dir: Path, start_month: str, end_month: str):

    df = _safe_read_parquet(summary_dir / "신규_년월.parquet")

    df["월"] = pd.to_datetime(
        df["계약시작월"],
        format="%Y.%m",
        errors="coerce"
    ).dt.to_period("M")

    df = df[df["계약유형분류"] != "케어십"]

    start = pd.Period(start_month.replace(".", "-"), freq="M")
    end = pd.Period(end_month.replace(".", "-"), freq="M")

    df = df[(df["월"] >= start) & (df["월"] <= end)]

    if df.empty:
        return df

    df["구분"] = df["재구독유형"].apply(_normalize_resubscribe_type)
    df["방문구분"] = df["서비스관리유형"].apply(_classify_visit_type)

    return df


# =========================================================
# 연도 상태
# =========================================================
def _init_year_expand_state(start_month, end_month):

    months = _month_range(start_month, end_month)
    years = sorted(set(m.year for m in months))
    end_year = pd.Period(end_month.replace(".", "-"), freq="M").year

    key = _range_state_key(start_month, end_month)

    if st.session_state.get("init_key") != key:
        for y in years:
            st.session_state[_year_state_key(y)] = (y >= end_year - 1)
        st.session_state["init_key"] = key


def _get_visible_columns_and_button_positions(start_month, end_month):

    months = _month_range(start_month, end_month)
    years = sorted(set(m.year for m in months))

    visible_cols = ["구분", "관리방식", "항목"]
    button_specs = []

    idx = 3

    for y in years:
        expanded = st.session_state.get(_year_state_key(y), False)
        ym = [m for m in months if m.year == y]

        if expanded:
            for m in ym:
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


def _render_year_toggle_row(visible_cols, button_specs):

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
                key=f"year_btn_{y}",
                use_container_width=True
            ):
                st.session_state[_year_state_key(y)] = not expanded
                st.rerun()


# =========================================================
# Matrix 생성
# =========================================================
def _build_matrix(df, start_month, end_month):

    months = _month_range(start_month, end_month)

    # 전체(판매수량)
    overall = df.copy()
    overall["구분"] = "판매수량"

    detail = df.copy()

    data = pd.concat([overall, detail])

    total_all = overall.groupby("월")["계정수"].sum().reindex(months, fill_value=0)

    total = data.groupby(["구분", "월"])["계정수"].sum().unstack(fill_value=0).reindex(columns=months)
    visit = data.groupby(["구분", "방문구분", "월"])["계정수"].sum().unstack(fill_value=0).reindex(columns=months)

    res = []
    years = sorted(set(m.year for m in months))

    def ysum(series, y):
        return series[[m for m in months if m.year == y]].sum()

    for tier in ["판매수량", "신규", "재구독"]:

        if tier not in total.index:
            continue

        ts = total.loc[tier]

        # 수량
        row = {"구분": tier, "관리방식": "", "항목": "수량"}

        for m in months:
            row[_format_month_col(m)] = _format_qty_thousand(ts[m])

        for y in years:
            row[_format_year_total_col(y)] = _format_qty_thousand(ysum(ts, y))

        res.append(row)

        # 신규/재구독만 %
        if tier != "판매수량":
            row = {"구분": "", "관리방식": "", "항목": "(%)"}

            for m in months:
                row[_format_month_col(m)] = _format_ratio(ts[m] / total_all[m]) if total_all[m] else "0%"

            for y in years:
                row[_format_year_total_col(y)] = _format_ratio(
                    ysum(ts, y) / ysum(total_all, y)
                ) if ysum(total_all, y) else "0%"

            res.append(row)

        # 방문/자가
        for vt in ["방문", "자가"]:

            vs = visit.loc[(tier, vt)] if (tier, vt) in visit.index else pd.Series(0, index=months)

            # 수량
            row = {"구분": "", "관리방식": vt, "항목": "수량"}

            for m in months:
                row[_format_month_col(m)] = _format_qty_thousand(vs[m])

            for y in years:
                row[_format_year_total_col(y)] = _format_qty_thousand(ysum(vs, y))

            res.append(row)

            # %
            row = {"구분": "", "관리방식": vt, "항목": "(%)"}

            for m in months:
                row[_format_month_col(m)] = _format_ratio(vs[m] / ts[m]) if ts[m] else "0%"

            for y in years:
                row[_format_year_total_col(y)] = _format_ratio(
                    ysum(vs, y) / ysum(ts, y)
                ) if ysum(ts, y) else "0%"

            res.append(row)

    return pd.DataFrame(res)


# =========================================================
# 스타일
# =========================================================
def _style(df):

    year_cols = [c for c in df.columns if c.endswith("년 누적")]

    def f(row):
        s = [""] * len(row)

        # ✅ 비중 → 초록
        if row["항목"] == "(%)":
            s = ["color:#0a7a0a" for _ in row]

        # ✅ 구분 bold
        if row["구분"] in ["판매수량", "신규", "재구독"] and row["항목"] == "수량":
            s = ["font-weight:bold" for _ in row]

        return s

    styler = df.style.apply(f, axis=1)

    # ✅ 연도누적 음영
    styler = styler.set_properties(
        subset=year_cols,
        **{"background-color": "#fff4cc", "font-weight": "bold"}
    )

    # ✅ 좌측 강조
    styler = styler.set_properties(
        subset=["구분", "관리방식", "항목"],
        **{"font-weight": "bold"}
    )

    return styler


# =========================================================
# 렌더
# =========================================================
def render_dashboard(context):

    summary_dir = Path(context["summary_dir"])
    start = context["start_month"]
    end = context["end_month"]

    st.markdown("## 방문주기별 판매수량(한국)")

    df = _load(summary_dir, start, end)

    if df.empty:
        st.warning("데이터 없음")
        return

    _init_year_expand_state(start, end)

    matrix = _build_matrix(df, start, end)

    visible_cols, button_specs = _get_visible_columns_and_button_positions(start, end)

    visible_cols = [c for c in visible_cols if c in matrix.columns]
    matrix = matrix[visible_cols]

    # ✅ 핵심: 이게 버튼 위치 잡아줌
    _render_year_toggle_row(visible_cols, button_specs)

    st.dataframe(
        _style(matrix),
        use_container_width=True,
        hide_index=True,
        height=750
    )