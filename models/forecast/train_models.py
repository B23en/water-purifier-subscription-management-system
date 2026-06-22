"""
[학습 코드] 데이터 로드 + 예측 모델 정의/학습
================================================
- 예측 대상: 신규 건수 / 해지 건수 / 재구독률(%)  (만기는 예측 아님 → 계약기간으로 확정계산)
- 데이터는 WATER_BASE_DIR(.env) 경로의 SummaryDB parquet에서 읽음.
  ※ 데이터 파일 자체는 git에 절대 올라가지 않음(.gitignore). 이 코드는 '읽기'만 함.
- 모델: naive / seasonal_naive / MA3 / ETS / ARIMA(1,1,1) / SARIMA(안정화) / ensemble
- 각 모델은 '과거 시계열(ytr) → 다음달 1-step 예측값' 함수로 통일.
실행(단독 학습 확인):  python train_models.py
"""
import os
import warnings
import numpy as np
import duckdb
warnings.filterwarnings("ignore")
from statsmodels.tsa.holtwinters import ExponentialSmoothing
from statsmodels.tsa.statespace.sarimax import SARIMAX

# ── 데이터 경로 (환경변수로만 주입, 데이터는 git 밖) ──
def _summary_dir():
    base = os.environ.get("WATER_BASE_DIR")
    if not base:
        raise RuntimeError(
            "환경변수 WATER_BASE_DIR 가 설정되지 않았습니다. 데이터 상위 폴더 경로를 지정하세요.\n"
            "  예) export WATER_BASE_DIR=/path/to/계정데이터   (PythonCode/.env 의 WATER_BASE_DIR 와 동일)\n"
            "  ※ 데이터 파일은 git에 포함되지 않습니다. 각자 로컬 경로로 주입하세요."
        )
    return os.path.join(base, "SummaryDB")

_DATE_COL = {"신규": "계약시작월", "해지": "해지완료월", "만기": "만기월"}

def load_series(target):
    """월총계(또는 재구독률) 시계열 로드 + 완전월(2020.01~2026.05) 게이트.
    target ∈ {신규, 해지, 재구독률}. 반환: (months[list], values[np.array])"""
    sd = _summary_dir()
    if target == "재구독률":
        p = os.path.join(sd, "신규_년월.parquet")
        q = (f"SELECT 계약시작월 m, "
             f"100.0*SUM(CASE WHEN 재구독유형='재구독' THEN 계정수 ELSE 0 END)/SUM(계정수) v "
             f"FROM read_parquet('{p}') GROUP BY 1 ORDER BY 1")
    else:
        c = _DATE_COL[target]
        p = os.path.join(sd, f"{target}_년월.parquet")
        q = f"SELECT \"{c}\" m, SUM(계정수) v FROM read_parquet('{p}') GROUP BY 1 ORDER BY 1"
    df = duckdb.query(q).df()
    df = df[(df.m >= "2020.01") & (df.m <= "2026.05")].reset_index(drop=True)  # 완전월만
    return df.m.tolist(), df.v.values.astype(float)

# ── 모델 정의 (학습 + 1-step 예측) ──
def fit_naive(y):   return float(y[-1])                 # 다음달 = 이번달
def fit_snaive(y):  return float(y[-12])                # 다음달 = 작년 같은달
def fit_ma3(y):     return float(np.mean(y[-3:]))       # 최근 3개월 평균
def fit_ets(y):                                          # Holt-Winters(수준+추세+계절)
    try:
        return float(ExponentialSmoothing(y, trend="add", seasonal="add",
                     seasonal_periods=12, damped_trend=True).fit().forecast(1)[0])
    except Exception:
        return float(y[-1])
def fit_arima(y):                                        # ARIMA(1,1,1) 안정화
    try:
        return float(SARIMAX(y, order=(1, 1, 1), enforce_stationarity=True,
                     enforce_invertibility=True).fit(disp=0).forecast(1)[0])
    except Exception:
        return float(y[-1])
def fit_sarima(y):                                       # SARIMA(1,1,1)(0,1,1,12) 안정화
    try:
        return float(SARIMAX(y, order=(1, 1, 1), seasonal_order=(0, 1, 1, 12),
                     enforce_stationarity=True, enforce_invertibility=True
                     ).fit(disp=0).forecast(1)[0])
    except Exception:
        return float(y[-1])
def fit_ensemble(y):                                     # ARIMA+ETS+MA3 평균
    return float(np.mean([fit_arima(y), fit_ets(y), fit_ma3(y)]))

MODELS = {
    "naive": fit_naive, "snaive": fit_snaive, "MA3": fit_ma3, "ETS": fit_ets,
    "ARIMA": fit_arima, "SARIMA": fit_sarima, "ensemble": fit_ensemble,
}

if __name__ == "__main__":
    # 단독 실행: 데이터 로드 + 각 모델이 '다음달'을 예측하는지 확인
    for t in ["신규", "해지", "재구독률"]:
        m, y = load_series(t)
        print(f"[{t}] {m[0]}~{m[-1]} ({len(y)}개월), 최근값={y[-1]:.1f}")
        for name, fn in MODELS.items():
            print(f"    {name:9s} 다음달 예측 = {fn(y):.1f}")
