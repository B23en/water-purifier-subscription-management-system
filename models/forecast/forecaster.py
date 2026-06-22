"""
[운영 예측 인터페이스] 선정된 챔피언 모델로 '다음달 예측값 + 신뢰구간'을 산출한다.
================================================================================
- 챔피언(1단계 백테스트로 선정): 신규=ARIMA(1,1,1), 해지=ETS(damped Holt-Winters), 재구독률=ARIMA(1,1,1)
- app.py 등 앱 코드가 forecast("신규") 한 줄로 호출할 수 있는 깨끗한 인터페이스.
- 1단계 모듈(train_models.py)의 load_series / 챔피언 fit 함수를 그대로 재사용(모델 중복정의 없음).
- 데이터는 git 밖. WATER_BASE_DIR 환경변수로만 주입(train_models 가 강제).
- 신뢰구간: 모델별 내장 구간을 섞지 않고, '최근 1-step 롤링 백테스트 오차'의 RMSE로 통일
  (경험적 예측오차, 편향 포함 → test_backtest.py 의 RMSE 정의와 일치). 표본에서 추정하므로
  z 대신 t분포를 써서 point ± t(df=n-1)·RMSE. 실제 빗나간 정도를 반영해 모델 간 일관적이며,
  '다음달 1-step'에만 유효(다중기간엔 미적용). 정밀 확률보장이 아니라 운영용 가늠자다.
실행(단독 확인):  python forecaster.py
"""
import os
import sys

import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 같은 폴더의 train_models 임포트
from train_models import load_series, fit_arima, fit_ets

# 타깃 → (표시명, 챔피언 fit 함수). 1단계 선정 결과와 일치.
CHAMPION = {
    "신규":     ("ARIMA(1,1,1)",     fit_arima),
    "해지":     ("ETS(damped HW)",   fit_ets),
    "재구독률": ("ARIMA(1,1,1)",     fit_arima),
}

# 백테스트 잔차 추정 시 학습구간 최소 길이(계절 ETS가 2주기=24개월 확보되도록).
_MIN_TRAIN = 24


class Forecaster:
    """타깃 하나의 챔피언 모델을 적합해 다음달 예측값과 신뢰구간을 낸다.

    사용:
        f = Forecaster("신규").load()
        result = f.predict()          # dict 반환
    또는 단축 함수 forecast("신규").
    """

    def __init__(self, target):
        if target not in CHAMPION:
            raise ValueError(f"target 은 {list(CHAMPION)} 중 하나여야 합니다. 받은 값: {target!r}")
        self.target = target
        self.model_name, self._fit = CHAMPION[target]
        self.months = None
        self.y = None

    def load(self):
        """WATER_BASE_DIR 의 데이터에서 월별 시계열 로드."""
        self.months, self.y = load_series(self.target)
        return self

    def _backtest_rmse(self, window=18):
        """최근 window개월 1-step 롤링 백테스트 오차의 RMSE(경험적 예측오차 폭).

        매 원점에서 과거(y[:t])만으로 학습→다음달 예측→실제와 비교(미래 미사용, 누수 가드).
        RMSE(0중심)는 편향(ME)까지 포함한 '실제 빗나간 폭'이라 test_backtest.py 의 RMSE 정의와
        일치하고, 편향이 있어도 구간을 과소평가하지 않는다.
        반환: (rmse, 사용한 원점 수). 표본이 2개 미만이면 ValueError(조용한 nan 방지).
        """
        y = self.y
        n = len(y)
        # 학습구간이 _MIN_TRAIN 이상이 되도록 백테스트 창을 제한.
        w = max(1, min(window, n - _MIN_TRAIN))
        errs = []
        for t in range(n - w, n):
            ytr = y[:t]                      # 과거(처음~직전달)만
            assert len(ytr) == t             # 누수 가드: 학습길이 == 원점 인덱스
            errs.append(self._fit(ytr) - y[t])
        if len(errs) < 2:
            raise ValueError(
                f"신뢰구간 추정에 필요한 백테스트 표본이 부족합니다(원점 {len(errs)}개). "
                f"시계열이 너무 짧습니다(현재 {n}개월, 최소 {_MIN_TRAIN + 2}개월 필요)."
            )
        errs = np.asarray(errs, dtype=float)
        rmse = float(np.sqrt(np.mean(errs ** 2)))
        return rmse, len(errs)

    def predict(self, alpha=0.05):
        """다음달(1-step) 예측값 + (1-alpha) 신뢰구간. dict 반환.

        구간 = point ± t(df=n-1)·RMSE_1step (경험적·정규가정·1-step 한정).
        """
        if self.y is None:
            self.load()
        point = self._fit(self.y)                       # 전체 과거로 다음달 1-step 예측
        rmse, n_err = self._backtest_rmse()
        # σ를 표본에서 추정하므로 z 대신 t분포(df=n_err-1). n 작을수록 구간이 정직하게 넓어짐.
        tcrit = float(stats.t.ppf(1 - alpha / 2, df=max(1, n_err - 1)))
        lower, upper = point - tcrit * rmse, point + tcrit * rmse

        # 재구독률은 비율(%) → 0~100 밖 불가. 클리핑하고, 잘렸으면 flag로 노출(왜곡 숨기지 않음).
        clipped = False
        if self.target == "재구독률":
            point = min(100.0, max(0.0, point))
            new_lo, new_hi = max(0.0, lower), min(100.0, upper)
            clipped = (new_lo != lower) or (new_hi != upper)
            lower, upper = new_lo, new_hi

        return {
            "target": self.target,
            "model": self.model_name,
            "horizon": "다음달(1-step)",             # 이 구간은 1개월 앞에만 유효
            "last_month": self.months[-1],          # 예측 기준월(이 달까지 관측)
            "prediction": round(float(point), 2),   # 다음달 예측값
            "lower": round(float(lower), 2),         # 신뢰구간 하한
            "upper": round(float(upper), 2),         # 신뢰구간 상한
            "interval_conf": round((1 - alpha) * 100),
            "error_rmse": round(float(rmse), 2),     # 경험적 1-step 오차 RMSE(편향 포함)
            "n_backtest": n_err,                      # 구간 추정에 쓴 원점 수
            "clipped": clipped,                       # 구간이 0~100 경계에서 잘렸는지
        }


def forecast(target, alpha=0.05):
    """단축 함수: 타깃의 다음달 예측값 + 신뢰구간 dict. app.py 가 이걸 호출하면 됨."""
    return Forecaster(target).load().predict(alpha=alpha)


if __name__ == "__main__":
    # 단독 실행: 세 타깃의 다음달 예측 + 95% 신뢰구간 확인
    for t in ["신규", "해지", "재구독률"]:
        r = forecast(t)
        flag = " [구간 0~100 경계 클리핑됨]" if r["clipped"] else ""
        print(f"[{r['target']:6s}] {r['model']:16s} | 기준월 {r['last_month']} → "
              f"{r['horizon']} 예측 {r['prediction']:>8} "
              f"({r['interval_conf']}% 구간 {r['lower']}~{r['upper']}, "
              f"RMSE={r['error_rmse']}, n={r['n_backtest']}){flag}")
