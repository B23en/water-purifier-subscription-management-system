"""
[Phase 1] 데이터 로더 + Δ계정수(MoM/YoY) 전처리
================================================
설계문서(ML_분석모델_설계문서.docx) 기준 동작:
- 신규/해지/만기는 각각 별도 SummaryDB(월×세그먼트조합 집계) — 따로 분석한다.
- 기준월 vs 비교월(전월=MoM, 전년동월=YoY) 두 시점의 세그먼트별 계정수를 맞춰서
  Δ계정수 = 계정수(기준월) - 계정수(비교월) 를 계산한다. 한쪽에만 있는 조합은 0으로 채움
  (세그먼트 조합 19,000여 개 중 대부분이 1~2개월만 나타나는 희소 데이터라,
   조합별로 81개월 전체 시계열을 이어붙이는 방식은 쓰지 않는다 — 매 기준월마다
   '그 시점 vs 비교 시점' 2개 스냅샷만 비교하는 방식)
- 모델 비교 실험(4모델)을 위해, 비교 가능한 모든 기준월에 대해 이 비교를 반복해
  쌓은 데이터셋을 만든다 (단일 기준월 분석이 아니라 전체 히스토리를 학습 데이터로 사용).
실행(단독 확인): python data_loader.py
"""
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import CANCEL_EXTRA_COL, SEGMENT_COLS, parquet_path

_DATE_COL = {"신규": "계약시작월", "해지": "해지완료월", "만기": "만기월"}


def segment_cols_for(target: str) -> list:
    """target별 세그먼트(피처) 컬럼 목록. 해지는 해지접수유형상세가 추가됨."""
    cols = list(SEGMENT_COLS)
    if target == "해지":
        cols = cols + [CANCEL_EXTRA_COL]
    return cols


def load_raw(target: str) -> pd.DataFrame:
    """SummaryDB parquet 로드, 날짜 컬럼을 공통명 '년월'로 통일."""
    df = pd.read_parquet(parquet_path(target))
    return df.rename(columns={_DATE_COL[target]: "년월"})


def _month_slice(df: pd.DataFrame, segment_cols: list, month: str) -> pd.DataFrame:
    """특정 월의 세그먼트별 계정수 (동일 조합이 중복되면 합산)."""
    sub = df[df["년월"] == month]
    return sub.groupby(segment_cols, as_index=False)["계정수"].sum()


def compute_delta(df: pd.DataFrame, segment_cols: list, ref_month: str, cmp_month: str) -> pd.DataFrame:
    """기준월 vs 비교월 세그먼트별 Δ계정수. 한쪽에만 있는 조합은 0으로 채움."""
    ref = _month_slice(df, segment_cols, ref_month).rename(columns={"계정수": "계정수_기준월"})
    cmp_ = _month_slice(df, segment_cols, cmp_month).rename(columns={"계정수": "계정수_비교월"})
    merged = ref.merge(cmp_, on=segment_cols, how="outer")
    merged[["계정수_기준월", "계정수_비교월"]] = merged[["계정수_기준월", "계정수_비교월"]].fillna(0)
    merged["Δ계정수"] = merged["계정수_기준월"] - merged["계정수_비교월"]
    merged["기준월"] = ref_month
    merged["비교월"] = cmp_month
    return merged


def _shift_month(month: str, n: int) -> str:
    """'YYYY.MM' 문자열을 n개월 이동 (MoM=-1, YoY=-12)."""
    p = pd.Period(month.replace(".", "-"), freq="M") + n
    return f"{p.year}.{p.month:02d}"


def build_dataset(target: str, kind: str = "MoM") -> pd.DataFrame:
    """전체 히스토리에 대해 기준월별 MoM/YoY Δ계정수 데이터셋을 쌓아서 반환.
    target: '신규' | '해지' | '만기'
    kind:   'MoM'(전월 대비) | 'YoY'(전년동월 대비)"""
    df = load_raw(target)
    segment_cols = segment_cols_for(target)
    months = sorted(df["년월"].unique())
    month_set = set(months)
    shift = -1 if kind == "MoM" else -12

    rows = []
    for m in months:
        cmp_month = _shift_month(m, shift)
        if cmp_month not in month_set:
            continue  # 히스토리 시작 구간 등 비교월 데이터가 없으면 스킵
        rows.append(compute_delta(df, segment_cols, m, cmp_month))
    if not rows:
        raise ValueError(f"{target}/{kind}: 비교 가능한 기준월이 없습니다.")
    out = pd.concat(rows, ignore_index=True)
    out["구분"] = kind
    return out


if __name__ == "__main__":
    for target in ["신규", "해지", "만기"]:
        for kind in ["MoM", "YoY"]:
            ds = build_dataset(target, kind)
            print(
                f"[{target}/{kind}] rows={len(ds):>6}  기준월수={ds['기준월'].nunique():>3}  "
                f"Δ계정수 평균={ds['Δ계정수'].mean():+.2f}  표준편차={ds['Δ계정수'].std():.2f}  "
                f"기준월범위={ds['기준월'].min()}~{ds['기준월'].max()}"
            )
