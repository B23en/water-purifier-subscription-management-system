"""
[Phase 0 확인용] 환경설정 스모크 테스트
================================================
- 목적: 의존성 설치 + WATER_BASE_DIR 설정 + 3개 parquet 파일 접근이 모두 정상인지 확인
- 실행: python check_env.py   (models/segment_shap/ 안에서, venv 활성화 상태로)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import FILES, parquet_path


def check_imports():
    mods = ["pandas", "pyarrow", "sklearn", "xgboost", "lightgbm",
            "catboost", "shap", "statsmodels", "duckdb", "dotenv"]
    missing = []
    for m in mods:
        try:
            __import__(m)
        except ImportError:
            missing.append(m)
    if missing:
        print(f"[FAIL] 설치 안 된 패키지: {missing}")
        print("       -> root requirements.txt 와 models/segment_shap/requirements.txt 둘 다 설치했는지 확인")
        return False
    print("[OK] 모든 라이브러리 import 성공")
    return True


def check_data():
    ok = True
    for target in FILES:
        p = parquet_path(target)
        if os.path.exists(p):
            print(f"[OK] {target}: {p}")
        else:
            print(f"[FAIL] {target} 파일 없음: {p}")
            ok = False
    return ok


if __name__ == "__main__":
    print("=== Phase 0 환경설정 확인 ===")
    ok1 = check_imports()
    print()
    try:
        ok2 = check_data()
    except RuntimeError as e:
        print(f"[FAIL] {e}")
        ok2 = False
    print()
    if ok1 and ok2:
        print("환경설정 끝! Phase 1(데이터 로더)로 넘어가면 됩니다.")
    else:
        print("위 [FAIL] 항목을 먼저 해결하세요.")
