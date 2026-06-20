# LG-국립창원대 연계 에이전트 시스템 개발 프로젝트

LG와 국립창원대학교가 연계하여 진행하는 에이전트 시스템 개발 프로젝트

## 📁 폴더 구조

| 폴더 | 설명 |
|------|------|
| `models/` | 비교분석 · 예측 모델 관련 파일 |
| `assets/` | 흐름도, 구조도 등 에셋 |
| `archived/` | 별도로 보관하는 파일 |
| `docs/` | 기획 · 명세 등 문서 |

## 🚀 개발 환경 구동

경로는 코드에 고정돼 있지 않고 **환경변수 `WATER_BASE_DIR`(데이터 루트)** 로 주입합니다.
설정하지 않으면 운영 기본값(`V:\한국 정수기 계정`)을 사용하므로 운영 환경은 변경이 필요 없습니다.

```bash
# 1) 의존성 설치
pip install streamlit pandas pyarrow matplotlib openpyxl python-dotenv openai

# 2) 환경 설정: PythonCode/.env.example 를 .env 로 복사 후 값 입력
#    - WATER_BASE_DIR: 로컬 데이터 루트 경로
#    - AZURE_OAI_* : 챗봇용(미설정 시 키워드 fallback 동작)

# 3) 데이터 루트 아래에 폴더 골격과 카테고리 CSV(0.Category/) 준비

# 4) 실행
cd PythonCode
streamlit run app.py
```

## ⚠️ 보안 주의

> **데이터 자체를 본 repo에 업로드하는 행위는 보안 문제로 절대 금지합니다.**
>
> 원천 데이터 및 민감 정보는 어떠한 경우에도 커밋 · 푸시하지 금지
