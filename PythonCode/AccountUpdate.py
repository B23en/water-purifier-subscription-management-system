import re
import shutil
from pathlib import Path

import pandas as pd

from channel_mapper import load_channel_map, apply_channel
from model_mapper import (
    load_model_map,
    apply_model,
    get_unknown_models,
    update_model_category,
)

# =========================================================
# 경로 설정
# =========================================================
BASE_DIR = Path(r"V:\한국 정수기 계정")
RAW_DIR = BASE_DIR / "1.RawData"
DONE_DIR = BASE_DIR / "1-1.RawData_Done"
OUT_DIR = BASE_DIR / "2.UpdatedData"

CHANNEL_FILE = BASE_DIR / "0.Category" / "SalesChannelCategory.csv"
MODEL_FILE = BASE_DIR / "0.Category" / "ModelCategory.csv"

DONE_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)


# =========================================================
# 데이터 유형별 설정
# =========================================================
COMMON_REQUIRED_COLS = [
    "계약번호", "구독제품군", "모델", "계약유형", "리스유형", "계약기간", "의무사용기간",
    "서비스관리유형", "서비스주기", "자재교환유형", "서비스사무소", "재구독유형",
    "원본계약번호", "BILLTO", "판매채널", "ERP주문번호", "청약요청번호", "결합상품여부", "계약시작일자"
]


DATASET_CONFIG = {
    "신규": {
        "required_cols": COMMON_REQUIRED_COLS,
        "priority_cols": COMMON_REQUIRED_COLS,
        "date_column": "계약시작일자",
    },

    "해지": {
        "required_cols": COMMON_REQUIRED_COLS + [
            "해지완료일자",
            "해지접수유형",
            "해지접수유형상세",
            "해지후사용방식",
        ],
        "priority_cols": COMMON_REQUIRED_COLS + [
            "해지완료일자",
            "해지접수유형",
            "해지접수유형상세",
            "해지후사용방식",
        ],
        "date_column": "해지완료일자",
    },

    "만기": {
        "required_cols": COMMON_REQUIRED_COLS + [
            "만기일자"
        ],
        "priority_cols": COMMON_REQUIRED_COLS + [
            "만기일자"
        ],
        "date_column": "만기일자",
    }
}



# =========================================================
# 공통 함수
# =========================================================
def normalize_columns(df):
    df = df.copy()
    df.columns = [str(c).strip().replace("\n", "").replace("\r", "") for c in df.columns]
    return df


def read_file_auto(path: Path):
    encodings = [
        "utf-16",
        "utf-16le",
        "utf-16be",
        "utf-8-sig",
        "cp949",
        "euc-kr",
        "utf-8"
    ]
    seps = [",", "\t", "|", ";"]

    last_error = None

    for enc in encodings:
        for sep in seps:
            try:
                df = pd.read_csv(path, dtype=str, encoding=enc, sep=sep)
                df = df.fillna("")
                df = normalize_columns(df)

                if len(df.columns) == 1:
                    continue

                return df
            except Exception as e:
                last_error = e

    raise ValueError(f"\n❌ 파일 읽기 실패\n경로: {path}\n마지막 오류: {last_error}")


def extract_month(x):
    m = re.search(r"(\d+)", str(x))
    return int(m.group(1)) if m else 0


def normalize_date(series):
    original = series.copy()
    s = pd.to_datetime(series, errors="coerce")
    out = s.dt.strftime("%Y-%m-%d")
    return out.where(~s.isna(), original)


def classify_contract_type(row):
    contract_type = str(row.get("계약유형", "")).strip()
    lease_type = str(row.get("리스유형", "")).strip()
    mandatory_period = str(row.get("의무사용기간", "")).strip()
    sales_channel = str(row.get("판매채널", "")).strip()
    erp_order = str(row.get("ERP주문번호", "")).strip()

    if contract_type == "가전구독":
        return lease_type

    if mandatory_period in ["", "0", "0개월"]:
        return "일반판매무상"

    cond1 = (
        erp_order == "" and
        sales_channel in ["LG케어십", "하이케어솔루션(B2C)", "LG케어십_B2B"]
    )

    if cond1:
        return "케어십"

    return "일반판매유상"


def apply_contract_columns(df, data_type):
    df = df.copy()

    if "계약기간" in df.columns:
        df["계약기간(년)"] = df["계약기간"].apply(lambda x: extract_month(x) // 12)
    else:
        df["계약기간(년)"] = ""

    if "의무사용기간" in df.columns:
        df["의무사용기간(년)"] = df["의무사용기간"].apply(lambda x: extract_month(x) // 12)
    else:
        df["의무사용기간(년)"] = ""

    df["계약유형분류"] = df.apply(classify_contract_type, axis=1)
    df["데이터구분"] = data_type

    for col in ["계약시작일자", "해지완료일자", "만기일자"]:
        if col in df.columns:
            df[col] = normalize_date(df[col])

    return df


def detect_data_type(df):
    cols = set(df.columns)

    if "해지완료일자" in cols:
        return "해지"

    if "만기일자" in cols:
        return "만기"

    return "신규"


def validate_required_columns(df, data_type):
    required_cols = DATASET_CONFIG[data_type]["required_cols"]
    missing = [c for c in required_cols if c not in df.columns]
    return missing


def reorder_columns(df, data_type):
    priority_cols = DATASET_CONFIG[data_type]["priority_cols"]

    derived_cols = [
        "데이터구분",
        "채널분류코드",
        "채널분류",
        "Tool",
        "모델명",
        "기능",
        "계약유형분류",
        "계약기간(년)",
        "의무사용기간(년)",
    ]

    ordered = [c for c in priority_cols + derived_cols if c in df.columns]
    extras = [c for c in df.columns if c not in ordered]
    return df[ordered + extras]


def get_output_paths(file_path: Path, data_type: str):
    out_dir = OUT_DIR / data_type
    done_dir = DONE_DIR / data_type

    out_dir.mkdir(parents=True, exist_ok=True)
    done_dir.mkdir(parents=True, exist_ok=True)

    out_file = out_dir / f"{file_path.stem}_{data_type}.parquet"
    done_file = done_dir / file_path.name

    return out_file, done_file


def run_account_update(file_path: Path, forced_type: str = "AUTO", new_model_rows=None):
    """
    Streamlit/app.py에서 호출하는 메인 함수

    반환 예시:
    1) 신규 모델 입력 필요
    {
        "status": "NEED_MODEL_INPUT",
        "unknown_models": [...]
    }

    2) 완료
    {
        "status": "DONE",
        "output_file": "...",
        "data_type": "신규"
    }

    3) 에러
    {
        "status": "ERROR",
        "message": "..."
    }
    """
    try:
        if not file_path.exists():
            return {"status": "ERROR", "message": f"원본 파일이 없습니다: {file_path}"}

        if not CHANNEL_FILE.exists():
            return {"status": "ERROR", "message": f"채널 분류 파일 없음: {CHANNEL_FILE}"}

        if not MODEL_FILE.exists():
            return {"status": "ERROR", "message": f"모델 분류 파일 없음: {MODEL_FILE}"}

        sales_map, billto_map = load_channel_map(CHANNEL_FILE)

        if new_model_rows:
            update_model_category(MODEL_FILE, new_model_rows)

        model_map = load_model_map(MODEL_FILE)

        df_raw = read_file_auto(file_path)

        data_type = detect_data_type(df_raw) if str(forced_type).upper() == "AUTO" else forced_type

        if data_type not in DATASET_CONFIG:
            return {"status": "ERROR", "message": f"지원하지 않는 데이터구분입니다: {data_type}"}

        missing = validate_required_columns(df_raw, data_type)
        if missing:
            return {
                "status": "ERROR",
                "message": f"필수 컬럼 누락: {missing}"
            }

        # 신규 모델 체크
        unknown_models = get_unknown_models(df_raw, model_map)
        if unknown_models:
            return {
                "status": "NEED_MODEL_INPUT",
                "unknown_models": unknown_models,
                "data_type": data_type
            }

        # 채널 / 모델 / 계약 파생
        df_raw = apply_channel(df_raw, sales_map, billto_map)
        df_raw = apply_model(df_raw, model_map)
        df_raw = apply_contract_columns(df_raw, data_type)
        df_raw = reorder_columns(df_raw, data_type)

        out_file, done_file = get_output_paths(file_path, data_type)

        df_raw.to_parquet(out_file, index=False, engine="pyarrow")

        if done_file.exists():
            done_file.unlink()

        shutil.move(str(file_path), str(done_file))

        return {
            "status": "DONE",
            "output_file": str(out_file),
            "done_file": str(done_file),
            "data_type": data_type,
            "row_count": len(df_raw),
        }

    except Exception as e:
        return {"status": "ERROR", "message": str(e)}