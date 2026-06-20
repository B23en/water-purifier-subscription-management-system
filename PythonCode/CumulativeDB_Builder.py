from pathlib import Path
import re
import pandas as pd

from config import BASE_DIR


# =========================================================
# 기본 경로
# =========================================================
SUMMARY_DIR = BASE_DIR / "SummaryDB"

BASE_FILE_NAME = "누적_2019.12.parquet"
OUTPUT_FILE_NAME = "누적_년월.parquet"

# ---------------------------------------------------------
# 누적 계산 기준 컬럼
# ---------------------------------------------------------
KEY_COLS = [
    "Tool",
    "모델명",
    "기능",
    "계약유형분류",
    "서비스관리유형",
    "서비스주기",
    "자재교환유형",
]

OUTPUT_COLS = [
    "기준월",
    "Tool",
    "모델명",
    "기능",
    "계약유형분류",
    "서비스관리유형",
    "서비스주기",
    "자재교환유형",
    "순증계정수",
    "누적계정수",
]


# =========================================================
# 유틸
# =========================================================
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


def normalize_month_str(value) -> str:
    """
    yyyy.mm 형식으로 통일
    """
    if pd.isna(value):
        return None

    s = str(value).strip()
    s = s.replace("-", ".").replace("/", ".")

    # 202001 형태
    if len(s) == 6 and s.isdigit():
        return f"{s[:4]}.{s[4:6]}"

    parts = s.split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}.{parts[1].zfill(2)}"

    try:
        dt = pd.to_datetime(s, errors="raise")
        return dt.strftime("%Y.%m")
    except Exception:
        return s


def ym_to_period(ym: str) -> pd.Period:
    return pd.Period(ym.replace(".", "-"), freq="M")


def extract_month_from_filename(file_name: str) -> str | None:
    """
    파일명에서 yyyy.mm / yyyy-mm / yyyymm 추출
    예:
    신규_2020.01.parquet
    해지_2020-01.parquet
    만기_202001.parquet
    """
    stem = Path(file_name).stem

    # 2020.01 / 2020-01
    m = re.search(r"(20\d{2})[.\-](\d{1,2})", stem)
    if m:
        return f"{m.group(1)}.{m.group(2).zfill(2)}"

    # 202001
    m = re.search(r"(20\d{2})(\d{2})", stem)
    if m:
        return f"{m.group(1)}.{m.group(2)}"

    return None


def ensure_key_cols(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # 자재교환유형 없으면 6개월
    if "자재교환유형" not in df.columns:
        df["자재교환유형"] = "6개월"
    else:
        df["자재교환유형"] = df["자재교환유형"].fillna("").astype(str).str.strip()
        df.loc[df["자재교환유형"] == "", "자재교환유형"] = "6개월"

    for col in KEY_COLS:
        if col not in df.columns:
            df[col] = ""

    for col in KEY_COLS:
        df[col] = df[col].fillna("").astype(str).str.strip()

    return df


def detect_value_col(df: pd.DataFrame) -> str:
    candidates = ["계정수", "신규계정수", "해지계정수", "만기계정수", "누적계정수"]
    for c in candidates:
        if c in df.columns:
            return c
    raise ValueError(f"계정수 관련 컬럼을 찾을 수 없습니다. 현재 컬럼: {list(df.columns)}")


# =========================================================
# 데이터 로드
# =========================================================
def load_base_cumulative(base_file_name=BASE_FILE_NAME, log_callback=None) -> pd.DataFrame:
    """
    2019.12 기초 누적 데이터 로드
    """
    base_path = SUMMARY_DIR / base_file_name
    if not base_path.exists():
        raise FileNotFoundError(f"기초 누적 파일이 없습니다: {base_path}")

    df = pd.read_parquet(base_path)
    df = normalize_columns(df)
    df = ensure_key_cols(df)

    if "기준월" not in df.columns:
        raise ValueError("기초 누적 파일에 '기준월' 컬럼이 없습니다.")

    df["기준월"] = df["기준월"].apply(normalize_month_str)

    if "누적계정수" not in df.columns:
        if "계정수" in df.columns:
            df = df.rename(columns={"계정수": "누적계정수"})
        else:
            raise ValueError("기초 누적 파일에 '누적계정수' 또는 '계정수' 컬럼이 없습니다.")

    df["누적계정수"] = pd.to_numeric(df["누적계정수"], errors="coerce").fillna(0)

    if "순증계정수" not in df.columns:
        df["순증계정수"] = 0

    df = df[OUTPUT_COLS].copy()

    if log_callback:
        log_callback(f"[기초 누적] 로드 완료: {base_file_name} / {len(df):,}행")

    return df


def load_monthly_summary_files(prefix: str, month_col_name: str, log_callback=None) -> pd.DataFrame:
    """
    신규/해지/만기 parquet 전체를 읽어 월별 집계 데이터 생성
    결과 컬럼:
    기준월 + KEY_COLS + 계정수
    """
    file_list = sorted(SUMMARY_DIR.glob(f"{prefix}_*.parquet"))
    file_list = [f for f in file_list if f.stem.startswith(f"{prefix}_")]

    if not file_list:
        if log_callback:
            log_callback(f"[{prefix}] 파일이 없습니다.")
        return pd.DataFrame(columns=["기준월"] + KEY_COLS + ["계정수"])

    all_rows = []

    for file_path in file_list:
        try:
            df = pd.read_parquet(file_path)
            df = normalize_columns(df)
            df = ensure_key_cols(df)

            if month_col_name in df.columns:
                df["기준월"] = df[month_col_name].apply(normalize_month_str)
            elif "기준월" in df.columns:
                df["기준월"] = df["기준월"].apply(normalize_month_str)
            else:
                inferred_month = extract_month_from_filename(file_path.name)
                if not inferred_month:
                    raise ValueError(f"기준월 컬럼도 없고 파일명에서도 월 추출 실패: {file_path.name}")
                df["기준월"] = inferred_month

            value_col = detect_value_col(df)

            temp = df[["기준월"] + KEY_COLS + [value_col]].copy()
            temp = temp.rename(columns={value_col: "계정수"})
            temp["계정수"] = pd.to_numeric(temp["계정수"], errors="coerce").fillna(0)

            temp = (
                temp.groupby(["기준월"] + KEY_COLS, as_index=False)["계정수"]
                .sum()
            )

            all_rows.append(temp)

            if log_callback:
                log_callback(f"[{prefix}] 로드 완료: {file_path.name} / {len(temp):,}행")

        except Exception as e:
            if log_callback:
                log_callback(f"[{prefix}] 로드 실패: {file_path.name} / {e}")

    if not all_rows:
        return pd.DataFrame(columns=["기준월"] + KEY_COLS + ["계정수"])

    result = pd.concat(all_rows, ignore_index=True)
    result = (
        result.groupby(["기준월"] + KEY_COLS, as_index=False)["계정수"]
        .sum()
    )
    return result


# =========================================================
# 월별 계산
# =========================================================
def build_month_net(df_new: pd.DataFrame, df_term: pd.DataFrame, df_exp: pd.DataFrame, target_month: str) -> pd.DataFrame:
    """
    특정 월 순증계정수 계산
    순증계정수 = 신규 - 해지 - 만기
    """
    new_m = df_new[df_new["기준월"] == target_month][KEY_COLS + ["계정수"]].copy()
    term_m = df_term[df_term["기준월"] == target_month][KEY_COLS + ["계정수"]].copy()
    exp_m = df_exp[df_exp["기준월"] == target_month][KEY_COLS + ["계정수"]].copy()

    if len(new_m) == 0:
        new_m = pd.DataFrame(columns=KEY_COLS + ["신규계정수"])
    else:
        new_m = new_m.rename(columns={"계정수": "신규계정수"})

    if len(term_m) == 0:
        term_m = pd.DataFrame(columns=KEY_COLS + ["해지계정수"])
    else:
        term_m = term_m.rename(columns={"계정수": "해지계정수"})

    if len(exp_m) == 0:
        exp_m = pd.DataFrame(columns=KEY_COLS + ["만기계정수"])
    else:
        exp_m = exp_m.rename(columns={"계정수": "만기계정수"})

    merged = pd.merge(new_m, term_m, on=KEY_COLS, how="outer")
    merged = pd.merge(merged, exp_m, on=KEY_COLS, how="outer")

    for col in ["신규계정수", "해지계정수", "만기계정수"]:
        if col not in merged.columns:
            merged[col] = 0
        merged[col] = pd.to_numeric(merged[col], errors="coerce").fillna(0)

    merged["순증계정수"] = merged["신규계정수"] - merged["해지계정수"] - merged["만기계정수"]
    merged["기준월"] = target_month

    return merged[["기준월"] + KEY_COLS + ["순증계정수"]]


def calculate_cumulative_for_month(prev_cum: pd.DataFrame, month_net: pd.DataFrame, target_month: str) -> pd.DataFrame:
    """
    당월 누적계정수 = 전월 누적계정수 + 당월 순증계정수
    """
    prev = prev_cum[KEY_COLS + ["누적계정수"]].copy()
    net = month_net[KEY_COLS + ["순증계정수"]].copy()

    merged = pd.merge(prev, net, on=KEY_COLS, how="outer")

    merged["누적계정수"] = pd.to_numeric(merged["누적계정수"], errors="coerce").fillna(0)
    merged["순증계정수"] = pd.to_numeric(merged["순증계정수"], errors="coerce").fillna(0)

    merged["누적계정수"] = merged["누적계정수"] + merged["순증계정수"]
    merged["기준월"] = target_month

    # 필요시 음수 0 보정 가능
    # merged.loc[merged["누적계정수"] < 0, "누적계정수"] = 0

    merged = merged[OUTPUT_COLS].copy()
    return merged


# =========================================================
# 메인 실행
# =========================================================
def run_cumulative_db_build_single_file(
    base_file_name: str = BASE_FILE_NAME,
    output_file_name: str = OUTPUT_FILE_NAME,
    start_month: str = "2020.01",
    progress_callback=None,
    log_callback=None,
):
    """
    결과를 한 파일(누적_년월.parquet)에 저장
    - 2019.12 기초 누적 포함
    - 2020.01부터 월별 누적 계산 결과 append
    """

    # 1. 기초 누적 로드
    base_cum = load_base_cumulative(base_file_name=base_file_name, log_callback=log_callback)

    # 2. 신규/해지/만기 전체 로드
    df_new = load_monthly_summary_files("신규", "계약시작월", log_callback=log_callback)
    df_term = load_monthly_summary_files("해지", "해지완료월", log_callback=log_callback)
    df_exp = load_monthly_summary_files("만기", "만기월", log_callback=log_callback)

    # 3. 계산 대상 월 목록
    all_months = sorted(
        set(df_new["기준월"].dropna().tolist())
        | set(df_term["기준월"].dropna().tolist())
        | set(df_exp["기준월"].dropna().tolist()),
        key=lambda x: ym_to_period(x)
    )

    all_months = [m for m in all_months if ym_to_period(m) >= ym_to_period(start_month)]

    total = len(all_months)

    if log_callback:
        log_callback(f"[대상월 수] {total}개월")

    # 4. 결과 적재
    result_frames = [base_cum.copy()]
    prev_cum = base_cum.copy()

    for idx, month in enumerate(all_months, start=1):
        if progress_callback:
            progress_callback(idx, total, f"{month} 누적 계산 중")

        month_net = build_month_net(df_new, df_term, df_exp, month)
        curr_cum = calculate_cumulative_for_month(prev_cum, month_net, month)

        result_frames.append(curr_cum)
        prev_cum = curr_cum.copy()

        if log_callback:
            net_sum = month_net["순증계정수"].sum() if len(month_net) else 0
            cum_sum = curr_cum["누적계정수"].sum() if len(curr_cum) else 0
            log_callback(
                f"[{month}] 계산 완료 | 순증합계={net_sum:,.0f} | 누적합계={cum_sum:,.0f} | 행수={len(curr_cum):,}"
            )

    # 5. 한 파일로 합치기
    final_df = pd.concat(result_frames, ignore_index=True)

    final_df["기준월_정렬"] = final_df["기준월"].apply(lambda x: ym_to_period(x))
    final_df = final_df.sort_values(["기준월_정렬"] + KEY_COLS).drop(columns=["기준월_정렬"]).reset_index(drop=True)

    output_path = SUMMARY_DIR / output_file_name
    final_df.to_parquet(output_path, index=False)

    if log_callback:
        log_callback(f"[최종 저장 완료] {output_path} / 총 {len(final_df):,}행")

    return {
        "status": "DONE",
        "output_file": output_file_name,
        "row_count": len(final_df),
        "month_count": len(all_months) + 1,  # 2019.12 포함
    }