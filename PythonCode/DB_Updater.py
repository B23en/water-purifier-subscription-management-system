import shutil
from pathlib import Path

import pandas as pd

from config import BASE_DIR


# =========================================================
# 경로 설정
# =========================================================
UPDATED_DIR = BASE_DIR / "2.UpdatedData"
UPDATED_DONE_DIR = BASE_DIR / "2-2.UpdatedData_Done"
DB_DIR = BASE_DIR / "3.KR_DB"

DATA_TYPES = ["신규", "해지", "만기"]

DATE_COLUMN_MAP = {
    "신규": "계약시작일자",
    "해지": "해지완료일자",
    "만기": "만기일자",
}

UPDATED_DONE_DIR.mkdir(parents=True, exist_ok=True)
DB_DIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# 공통 함수
# =========================================================
def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip().replace("\n", "").replace("\r", "") for c in df.columns]
    return df


def normalize_date_column(df: pd.DataFrame, col_name: str) -> pd.DataFrame:
    df = df.copy()
    if col_name in df.columns:
        df[col_name] = pd.to_datetime(df[col_name], errors="coerce")
    return df


def load_parquet_file(file_path: Path) -> pd.DataFrame:
    df = pd.read_parquet(file_path)
    df = normalize_columns(df)
    df = df.fillna("")
    return df


def get_target_files(data_type: str):
    source_dir = UPDATED_DIR / data_type
    if not source_dir.exists():
        return []

    files = sorted(source_dir.glob("*.parquet"))
    return files


def split_by_year(df: pd.DataFrame, date_col: str):
    df = df.copy()
    df = normalize_date_column(df, date_col)

    if date_col not in df.columns:
        return {}

    valid_df = df[df[date_col].notna()].copy()
    if valid_df.empty:
        return {}

    valid_df["연도"] = valid_df[date_col].dt.year.astype(str)

    year_dict = {}
    for year, group in valid_df.groupby("연도"):
        group = group.drop(columns=["연도"], errors="ignore").copy()
        year_dict[year] = group

    return year_dict


def ensure_contract_no(df: pd.DataFrame, file_path: Path):
    if "계약번호" not in df.columns:
        raise ValueError(f"❌ '계약번호' 컬럼이 없습니다: {file_path}")


def get_db_file_path(data_type: str, year: str) -> Path:
    year_dir = DB_DIR / data_type / year
    year_dir.mkdir(parents=True, exist_ok=True)
    return year_dir / f"KR_DB_{data_type}_{year}.parquet"


def deduplicate_keep_existing(existing_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    existing_df = existing_df.copy()
    new_df = new_df.copy()

    existing_df["계약번호"] = existing_df["계약번호"].astype(str).str.strip()
    new_df["계약번호"] = new_df["계약번호"].astype(str).str.strip()

    existing_df = existing_df.drop_duplicates(subset=["계약번호"], keep="first")
    new_df = new_df.drop_duplicates(subset=["계약번호"], keep="first")

    existing_keys = set(existing_df["계약번호"].tolist())
    new_append = new_df[~new_df["계약번호"].isin(existing_keys)].copy()

    result = pd.concat([existing_df, new_append], ignore_index=True)
    result = result.drop_duplicates(subset=["계약번호"], keep="first")

    return result


def save_yearly_db(data_type: str, year: str, new_df: pd.DataFrame, logs: list):
    db_file = get_db_file_path(data_type, year)

    if db_file.exists():
        existing_df = pd.read_parquet(db_file)
        existing_df = normalize_columns(existing_df)
        existing_df = existing_df.fillna("")
        ensure_contract_no(existing_df, db_file)

        merged_df = deduplicate_keep_existing(existing_df, new_df)

        before_cnt = len(existing_df)
        after_cnt = len(merged_df)
        added_cnt = after_cnt - before_cnt

        merged_df.to_parquet(db_file, index=False)

        logs.append(f"   - 기존 DB 존재: {db_file.name}")
        logs.append(f"   - 기존 건수: {before_cnt:,}")
        logs.append(f"   - 추가 건수: {added_cnt:,}")
        logs.append(f"   - 최종 건수: {after_cnt:,}")

    else:
        new_df = new_df.copy()
        new_df["계약번호"] = new_df["계약번호"].astype(str).str.strip()
        new_df = new_df.drop_duplicates(subset=["계약번호"], keep="first")
        new_df.to_parquet(db_file, index=False)

        logs.append(f"   - 신규 DB 생성: {db_file.name}")
        logs.append(f"   - 저장 건수: {len(new_df):,}")


def move_processed_file(file_path: Path, data_type: str, logs: list):
    done_dir = UPDATED_DONE_DIR / data_type
    done_dir.mkdir(parents=True, exist_ok=True)

    target_path = done_dir / file_path.name

    if target_path.exists():
        target_path.unlink()

    shutil.move(str(file_path), str(target_path))
    logs.append(f"✅ 원본 이동 완료: {target_path}")


def process_one_file(file_path: Path, data_type: str, logs: list):
    logs.append(f"\n{'=' * 90}")
    logs.append(f"[처리 시작] {data_type} | {file_path.name}")

    date_col = DATE_COLUMN_MAP[data_type]

    df = load_parquet_file(file_path)
    ensure_contract_no(df, file_path)

    if date_col not in df.columns:
        raise ValueError(f"❌ 날짜 기준 컬럼이 없습니다. data_type={data_type}, required={date_col}")

    year_dict = split_by_year(df, date_col)

    if not year_dict:
        logs.append(f"⚠ 유효한 날짜 데이터가 없어 DB 적재를 건너뜁니다: {file_path.name}")
        move_processed_file(file_path, data_type, logs)
        return

    for year, year_df in sorted(year_dict.items()):
        logs.append(f"\n📌 연도 처리: {year}")
        save_yearly_db(data_type, year, year_df, logs)

    move_processed_file(file_path, data_type, logs)

    logs.append(f"[처리 완료] {file_path.name}")
    logs.append(f"{'=' * 90}")


def process_data_type(data_type: str, logs: list):
    logs.append(f"\n\n############## [{data_type}] 처리 시작 ##############")

    files = get_target_files(data_type)

    if not files:
        logs.append(f"처리할 파일이 없습니다: {UPDATED_DIR / data_type}")
        return

    success = 0
    fail = 0

    for file_path in files:
        try:
            process_one_file(file_path, data_type, logs)
            success += 1
        except Exception as e:
            fail += 1
            logs.append(f"\n❌ 처리 실패: {file_path.name}")
            logs.append(f"오류 내용: {e}")

    logs.append(f"\n[{data_type}] 처리 결과")
    logs.append(f"- 성공: {success}건")
    logs.append(f"- 실패: {fail}건")
    logs.append(f"############## [{data_type}] 처리 종료 ##############")


def run_db_update(selected_types=None):
    logs = []

    if selected_types is None:
        selected_types = DATA_TYPES

    logs.append("누적 DB 적재 작업을 시작합니다.")
    logs.append(f"- 원본 경로: {UPDATED_DIR}")
    logs.append(f"- 누적 DB 경로: {DB_DIR}")
    logs.append(f"- 완료 이동 경로: {UPDATED_DONE_DIR}")

    for data_type in selected_types:
        process_data_type(data_type, logs)

    logs.append("\n전체 작업 종료")
    return logs