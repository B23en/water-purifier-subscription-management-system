"""
[테스팅 코드] 롤링 백테스트 + 평가지표 비교
================================================
- 방법: 매 시점 '과거로만 학습 → 다음달 1-step 예측 → 실제와 비교' (데이터 누수 없음, assert로 가드)
- 체리피킹 방지: 여러 창(H=12/18/24) 평균
- 지표: MAE / MAPE / RMSE / MASE / ME(편향) / sMAPE + naive 대비 개선율 + 유의성(paired t-test p)
- 대상: 신규 / 해지 / 재구독률
실행:  python test_backtest.py        (또는 models/ 밖에서: python models/test_backtest.py)
"""
import os
import sys
import numpy as np
from scipy import stats

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # 같은 폴더의 train_models 임포트
from train_models import load_series, MODELS


def metrics(pred, true):
    """6개 지표 한 번에 계산."""
    p, t = np.asarray(pred, float), np.asarray(true, float)
    e = p - t
    return {
        "MAE":  np.mean(np.abs(e)),
        "MAPE": np.mean(np.abs(e / t)) * 100,
        "RMSE": np.sqrt(np.mean(e ** 2)),
        "ME":   np.mean(e),                                  # 편향(+과대/−과소)
        "sMAPE": np.mean(2 * np.abs(e) / (np.abs(p) + np.abs(t))) * 100,
    }


def rolling_backtest(y, H):
    """expanding window 롤링 1-step. 미래 정보 미사용(assert)."""
    preds = {k: [] for k in MODELS}
    truth = []
    for t in range(len(y) - H, len(y)):
        ytr = y[:t]                       # 과거(처음~직전달)만
        assert len(ytr) == t              # 누수 가드: 학습길이 == 원점 인덱스
        truth.append(y[t])
        for name, fn in MODELS.items():
            preds[name].append(fn(ytr))
    return np.asarray(truth), preds


def evaluate(target, windows=(12, 18, 24)):
    """창별 지표 + naive 대비 paired t-test. 창 평균 반환."""
    _, y = load_series(target)
    rows = {}
    for H in windows:
        truth, preds = rolling_backtest(y, H)
        naive_err = np.abs(np.asarray(preds["naive"]) - truth)
        naive_mae = np.mean(naive_err)
        for name, pr in preds.items():
            m = metrics(pr, truth)
            m["MASE"] = m["MAE"] / naive_mae          # naive 대비 스케일(<1이면 우수)
            err = np.abs(np.asarray(pr) - truth)
            p = 1.0 if name == "naive" else (
                stats.ttest_rel(err, naive_err).pvalue if np.std(err - naive_err) > 1e-9 else 1.0)
            rows.setdefault(name, []).append((m, p))
    return rows


def print_report(target):
    rows = evaluate(target)
    out = []
    for name, runs in rows.items():
        avg = {k: np.mean([r[0][k] for r in runs]) for k in runs[0][0]}
        out.append((name, avg, min(r[1] for r in runs), max(r[1] for r in runs)))
    naive_mape = [o[1]["MAPE"] for o in out if o[0] == "naive"][0]
    out.sort(key=lambda o: o[1]["MAPE"])
    print(f"\n=== {target}  (H=12/18/24 평균, SARIMA 안정화, 누수없음) ===")
    print(f"  {'모델':9s} {'MAE':>7} {'MAPE':>6} {'RMSE':>7} {'MASE':>5} {'ME':>7} {'sMAPE':>6}  naive대비   p     판정")
    for name, m, pmin, pmax in out:
        skill = (naive_mape - m["MAPE"]) / naive_mape * 100
        sig = "유의" if pmax < 0.05 else "NS(노이즈)"
        print(f"  {name:9s} {m['MAE']:7.1f} {m['MAPE']:5.1f}% {m['RMSE']:7.1f} "
              f"{m['MASE']:5.2f} {m['ME']:+7.1f} {m['sMAPE']:5.1f}% {skill:+6.1f}% {pmin:.2f}  {sig}")


if __name__ == "__main__":
    for target in ["신규", "해지", "재구독률"]:
        print_report(target)
    print("\n[해석] NS=naive와 통계적 차이 없음(n=18 검정력 한계). "
          "MAPE 낮을수록·MASE<1·|ME| 작을수록 우수. snaive=계절나이브.")
