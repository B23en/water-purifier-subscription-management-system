"""
세그먼트 Δ계정수 회귀 + SHAP 비교실험 모듈 — 공통 설정
================================================
- WATER_BASE_DIR(.env) 경로 하위 SummaryDB의 신규/해지/만기_년월.parquet 사용
- 데이터 파일 자체는 git에 절대 포함하지 않음(.gitignore) — 이 코드는 '읽기'만 함
- models/forecast/(전체 합계 시계열 예측, 별도 워크스트림)와는 무관 — 세그먼트별 회귀+SHAP 전용
"""
import os

from dotenv import load_dotenv

load_dotenv()  # repo 어디서 실행해도 상위 폴더의 .env를 찾아 로드

# 회귀 모델의 피처로 사용할 세그먼트 컬럼 (설계문서 기준)
SEGMENT_COLS = [
    "채널분류", "Tool", "모델명", "기능", "계약유형분류",
    "계약기간(년)", "서비스관리유형", "서비스주기", "자재교환유형",
    "서비스사무소", "재구독유형",
]
CANCEL_EXTRA_COL = "해지접수유형상세"  # 해지 데이터에만 추가되는 세그먼트 컬럼

FILES = {
    "신규": "신규_년월.parquet",
    "해지": "해지_년월.parquet",
    "만기": "만기_년월.parquet",
}


def summary_dir() -> str:
    base = os.environ.get("WATER_BASE_DIR")
    if not base:
        raise RuntimeError(
            "환경변수 WATER_BASE_DIR 가 설정되지 않았습니다. 데이터 상위 폴더 경로를 지정하세요.\n"
            "  예) repo 루트 .env 파일에 WATER_BASE_DIR=C:\\WaterData\\한국 정수기 계정\n"
            "  ※ 데이터 파일은 git에 포함되지 않습니다. 각자 로컬 경로로 주입하세요."
        )
    return os.path.join(base, "SummaryDB")


def parquet_path(target: str) -> str:
    if target not in FILES:
        raise ValueError(f"target은 {list(FILES)} 중 하나여야 합니다: {target}")
    return os.path.join(summary_dir(), FILES[target])
