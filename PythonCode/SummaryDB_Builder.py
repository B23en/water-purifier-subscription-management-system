from pathlib import Path
import pandas as pd


# =========================================================
# 기본 경로
# =========================================================
BASE_DIR = Path(r"V:\한국 정수기 계정")
KR_DB_DIR = BASE_DIR / "3.KR_DB"
SUMMARY_DIR = BASE_DIR / "SummaryDB"

SUMMARY_DIR.mkdir(parents=True, exist_ok=True)

# =========================================================
# 공통 컬럼 정의
# =========================================================
ID_COL = "계약번호"

BASE_GROUP_COLS = [
    "채널분류",
    "Tool",
    "모델명",
    "기능",
    "계약유형분류",
    "계약기간(년)",
    "서비스관리유형",
    "서비스주기",
    "자재교환유형",
    "서비스사무소",
    "재구독유형",
]

TYPE_CONFIG = {
    "신규": {
        "folder": "신규",
        "date_col": "계약시작일자",
        "month_col": "계약시작월",
        "group_cols": BASE_GROUP_COLS,
        "output_name": "신규_년월.parquet",   # ✅ 변경
    },
    "해지": {
        "folder": "해지",
        "date_col": "해지완료일자",
        "month_col": "해지완료월",
        "group_cols": BASE_GROUP_COLS + ["해지접수유형상세"],
        "output_name": "해지_년월.parquet",   # ✅ 변경
    },
    "만기": {
        "folder": "만기",
        "date_col": "만기일자",
        "month_col": "만기월",
        "group_cols": BASE_GROUP_COLS,
        "output_name": "만기_년월.parquet",   # ✅ 변경
    },
}


# =========================================================
# 유틸
# =========================================================
def log_safe(log_callback, message: str):
    if log_callback:
        log_callback(message)


def progress_safe(progress_callback, current: int, total: int, message: str):
    if progress_callback:
        progress_callback(current, total, message)


def get_available_years(selected_types=None):

    if not selected_types:
        selected_types = list(TYPE_CONFIG.keys())

    years = set()
    for data_type in selected_types:
        type_dir = KR_DB_DIR / TYPE_CONFIG[data_type]["folder"]
        if not type_dir.exists():
            continue

        for p in type_dir.iterdir():
            if p.is_dir():
                years.add(p.name)

    return sorted(years)


def get_source_files(data_type: str, selected_years=None):

    config = TYPE_CONFIG[data_type]
    type_dir = KR_DB_DIR / config["folder"]

    if not type_dir.exists():
        return []

    targets = []
    for year_dir in sorted(type_dir.iterdir(), key=lambda x: x.name):
        if not year_dir.is_dir():
            continue

        year_name = year_dir.name
        if selected_years and year_name not in selected_years:
            continue

        for pattern in ["*.csv", "*.txt", "*.xlsx", "*.xls", "*.parquet"]:
            for f in sorted(year_dir.glob(pattern), key=lambda x: x.name):
                targets.append({
                    "type": data_type,
                    "year": year_name,
                    "path": f
                })

    return targets


def read_table_safely(file_path: Path, required_cols):
    ext = file_path.suffix.lower()

    if ext == ".parquet":
        df = pd.read_parquet(file_path)

    elif ext in [".xlsx", ".xls"]:
        df = pd.read_excel(
            file_path,
            engine="openpyxl" if ext == ".xlsx" else None
        )

    else:
        df = pd.read_csv(
            file_path,
            encoding="utf-8-sig",
            low_memory=True
        )

    df.columns = [str(c).strip() for c in df.columns]

    existing_cols = [c for c in required_cols if c in df.columns]
    df = df[existing_cols].copy()

    for c in required_cols:
        if c not in df.columns:
            df[c] = pd.NA

    return df


# ✅ 년월 안정화 유지 (기존 반영)
def build_month_col(df: pd.DataFrame, date_col: str, month_col: str):

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")

    df[month_col] = (
        df[date_col]
        .dt.to_period("M")
        .astype(str)
        .str.replace("-", ".", regex=False)
    )

    return df


def summarize_one_file(df: pd.DataFrame, data_type: str):

    config = TYPE_CONFIG[data_type]
    date_col = config["date_col"]
    month_col = config["month_col"]
    group_cols = [month_col] + config["group_cols"]

    df = build_month_col(df, date_col, month_col)

    df = df[df[ID_COL].notna()].copy()
    df = df[df[month_col].notna()].copy()

    if df.empty:
        return pd.DataFrame(columns=group_cols + ["계정수"])

    result = (
        df.groupby(group_cols, dropna=False)[ID_COL]
        .nunique()
        .reset_index(name="계정수")
    )

    return result


def build_summary_for_type(
    data_type: str,
    selected_years=None,
    progress_callback=None,
    log_callback=None,
):

    config = TYPE_CONFIG[data_type]
    source_files = get_source_files(data_type, selected_years=selected_years)

    required_cols = list(set(
        [ID_COL, config["date_col"]] + config["group_cols"]
    ))

    partial_frames = []

    for item in source_files:
        file_path = item["path"]

        df = read_table_safely(file_path, required_cols=required_cols)
        summarized = summarize_one_file(df, data_type=data_type)

        if not summarized.empty:
            partial_frames.append(summarized)

    month_col = config["month_col"]
    group_cols = [month_col] + config["group_cols"]

    if partial_frames:
        final_df = pd.concat(partial_frames, ignore_index=True)

        final_df = (
            final_df.groupby(group_cols, dropna=False)["계정수"]
            .sum()
            .reset_index()
        )

        final_df["계정수"] = final_df["계정수"].astype("int64")

    else:
        final_df = pd.DataFrame(columns=group_cols + ["계정수"])

    # ✅ ✅ ✅ 핵심 변경: Parquet 저장
    output_file = SUMMARY_DIR / config["output_name"]

    final_df.to_parquet(
        output_file,
        index=False,
        engine="pyarrow",
        compression="snappy"
    )

    return {
        "status": "DONE",
        "data_type": data_type,
        "output_file": str(output_file),
        "file_count": len(source_files),
        "row_count": len(final_df),
    }


def run_summary_db_build(
    selected_types=None,
    selected_years=None,
    progress_callback=None,
    log_callback=None,
):

    if not selected_types:
        selected_types = ["신규", "해지", "만기"]

    results = []
    for data_type in selected_types:
        result = build_summary_for_type(
            data_type=data_type,
            selected_years=selected_years,
            progress_callback=progress_callback,
            log_callback=log_callback,
        )
        results.append(result)

    return results