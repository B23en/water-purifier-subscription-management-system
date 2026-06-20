"""
경로 설정 (환경 독립)

- 데이터 루트(BASE_DIR)는 환경변수 WATER_BASE_DIR 로 주입한다.
- 환경변수가 없으면 기존 운영 경로(V:\\한국 정수기 계정)를 기본값으로 사용한다.
  → 운영(V:) 환경은 아무것도 설정하지 않아도 그대로 동작한다.
- 개발 환경에서는 .env 또는 OS 환경변수에 WATER_BASE_DIR 를 지정한다.
  예) WATER_BASE_DIR=C:\\dev\\water_data
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 코드 위치(PythonCode/)의 .env 를 명시적으로 로드 (실행 cwd 와 무관하게 동작)
CODE_DIR = Path(__file__).resolve().parent
load_dotenv(CODE_DIR / ".env")

# 데이터 루트: 환경변수 우선, 없으면 기존 운영 경로
BASE_DIR = Path(os.getenv("WATER_BASE_DIR", r"V:\한국 정수기 계정"))

# 코드 자산(로고)은 데이터 루트가 아니라 코드 옆에 위치
LOGO_FILE = CODE_DIR / "IX2.0.jpg"
