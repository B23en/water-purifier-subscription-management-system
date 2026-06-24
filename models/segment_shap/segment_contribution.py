# [Phase 7] 세그먼트 기여도 분석 (Segment Contribution Analysis)
# ================================================
# XGBoost 없이 직접 분석:
# "어떤 세그먼트가 신규/해지 변화를 가장 많이 주도하는가?"
#
# 분석 방법:
#   1) 세그먼트 컬럼별 그룹 단위 월별 YoY 델타계정수 계산
#   2) 각 그룹의 기여도 3가지 측정:
#      - mean_abs_delta : 평균 절대 변화량
#      - share_pct      : 전체 |delta| 대비 이 그룹의 |delta| 비중 (%)
#      - corr_with_total: 그룹 delta와 전체 delta의 상관계수
#   3) 세그먼트 컬럼별 랭킹 -> 가장 영향력 있는 컬럼과 그룹 식별
#
# 실행:
#   python models/segment_shap/segment_contribution.py              # 전체 트렌드
#   python models/segment_shap/segment_contribution.py --month 2024.03 --target 신규
import os, sys, warnings
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_loader import load_raw, _shift_month
from config import SEGMENT_COLS, CANCEL_EXTRA_COL

warnings.filterwarnings("ignore")
plt.rcParams["font.family"]      = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "contribution_outputs")

# ── 필터링 기준 ───────────────────────────────────────────────
# 비중이 이 값을 넘으면 "구조적 지배" → 원래부터 압도적으로 많아서 같이 움직이는 것
DOMINANCE_THRESHOLD = 80.0
# 상관계수가 이 값 미만이면 전체 흐름과 무관 → 분석 의미 낮음
MIN_CORR = 0.5


# ── 월별 YoY Δ 계산 ────────────────────────────────────────────
def build_monthly_delta(target: str, seg_col: str) -> pd.DataFrame:
    """
    seg_col 기준 그룹별 월별 YoY Δ계정수 테이블.
    반환: pivot DataFrame, index=년월, columns=그룹명
    """
    df  = load_raw(target)
    agg = (
        df.groupby([seg_col, "년월"], observed=True)["계정수"]
        .sum().reset_index()
    )
    months    = sorted(agg["년월"].unique())
    month_set = set(months)

    rows = []
    for m in months:
        cmp_m = _shift_month(m, -12)
        if cmp_m not in month_set:
            continue
        cur = agg[agg["년월"] == m].set_index(seg_col)["계정수"]
        prv = agg[agg["년월"] == cmp_m].set_index(seg_col)["계정수"]
        all_groups = cur.index.union(prv.index)
        delta = cur.reindex(all_groups).fillna(0) - prv.reindex(all_groups).fillna(0)
        delta.name = m
        rows.append(delta)

    pivot = pd.DataFrame(rows).fillna(0)
    pivot.index.name = "년월"
    return pivot


# ── 기여도 계산 ───────────────────────────────────────────────
def compute_contribution(pivot: pd.DataFrame) -> pd.DataFrame:
    """
    pivot: index=년월, columns=그룹명, values=YoY Δ계정수
    각 그룹의 기여도 지표 반환
    """
    total = pivot.sum(axis=1)           # 전체 Δ (월별)
    total_abs_sum = pivot.abs().sum().sum()

    records = []
    for grp in pivot.columns:
        series = pivot[grp]
        mean_abs = series.abs().mean()
        share    = (series.abs().sum() / total_abs_sum * 100) if total_abs_sum > 0 else 0
        corr     = series.corr(total) if total.std() > 0 else 0

        # 방향: 주로 증가(+) vs 감소(-) 방향인지
        mean_dir = series.mean()

        records.append({
            "group":           grp,
            "mean_abs_delta":  round(mean_abs, 2),
            "share_pct":       round(share, 2),
            "corr_with_total": round(corr, 3),
            "mean_direction":  round(mean_dir, 2),
        })

    df = pd.DataFrame(records).sort_values("share_pct", ascending=False)
    df["rank"] = range(1, len(df) + 1)
    return df


# ── 세그먼트 컬럼별 전체 비교 ─────────────────────────────────
def rank_segment_cols(target: str) -> pd.DataFrame:
    """
    모든 세그먼트 컬럼을 돌면서 '어떤 컬럼이 가장 많은 분산을 포함하는지' 측정.
    분산 기준: 전체 Δ 중 top-1 그룹의 share_pct
    """
    cols = list(SEGMENT_COLS)
    if target == "해지":
        cols = cols + [CANCEL_EXTRA_COL]

    records = []
    for col in cols:
        try:
            pivot = build_monthly_delta(target, col)
            contrib = compute_contribution(pivot)
            top1 = contrib.iloc[0]
            records.append({
                "seg_col":        col,
                "n_groups":       len(contrib),
                "top1_group":     top1["group"],
                "top1_share_pct": top1["share_pct"],
                "top1_corr":      top1["corr_with_total"],
                "top1_mean_abs":  top1["mean_abs_delta"],
                # 구조적 지배: 한 그룹이 80% 이상 → 원래부터 압도적으로 많은 것
                "is_dominated":   top1["share_pct"] >= DOMINANCE_THRESHOLD,
            })
        except Exception as e:
            records.append({"seg_col": col, "error": str(e)})

    df = pd.DataFrame(records)
    if "top1_share_pct" not in df.columns:
        raise RuntimeError("모든 세그먼트 컬럼 분석 실패. 데이터 경로(.env WATER_BASE_DIR)를 확인하세요.")
    df = df.dropna(subset=["top1_share_pct"])
    return df.sort_values("top1_share_pct", ascending=False).reset_index(drop=True)


# ── 시각화 ────────────────────────────────────────────────────
def plot_ranking(contrib: pd.DataFrame, target: str, seg_col: str):
    """세그먼트 컬럼 내 그룹별 기여도 bar chart."""
    os.makedirs(OUT_DIR, exist_ok=True)
    top = contrib.head(10)

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))

    # 1) share_pct
    ax = axes[0]
    colors = ["#E74C3C" if v < 0 else "#3498DB" for v in top["mean_direction"]]
    ax.barh(top["group"][::-1], top["share_pct"][::-1], color=colors[::-1])
    ax.set_xlabel("전체 |Δ| 대비 비중 (%)")
    ax.set_title("기여 비중")

    # 2) mean_abs_delta
    ax = axes[1]
    ax.barh(top["group"][::-1], top["mean_abs_delta"][::-1], color="#2ECC71")
    ax.set_xlabel("평균 절대 변화량 (계정수)")
    ax.set_title("평균 변화 크기")

    # 3) corr_with_total
    ax = axes[2]
    bar_colors = ["#E74C3C" if v < 0 else "#9B59B6" for v in top["corr_with_total"]]
    ax.barh(top["group"][::-1], top["corr_with_total"][::-1], color=bar_colors[::-1])
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_xlabel("전체 Δ와의 상관계수")
    ax.set_title("전체 흐름 동조 여부")
    ax.set_xlim(-1.1, 1.1)

    plt.suptitle(f"{target} — [{seg_col}] 그룹별 기여도 분석", fontsize=13, fontweight="bold")
    plt.tight_layout()
    path = os.path.join(OUT_DIR, f"ranking_{target}_{seg_col}.png")
    plt.savefig(path, dpi=130); plt.close()
    print(f"  저장: {path}")


def plot_monthly_stacked(pivot: pd.DataFrame, contrib: pd.DataFrame,
                          target: str, seg_col: str, top_n: int = 5):
    """월별 YoY Δ 기여 추이 (stacked bar — top N 그룹 + 기타)."""
    os.makedirs(OUT_DIR, exist_ok=True)
    top_groups = contrib.head(top_n)["group"].tolist()

    plot_df = pivot[top_groups].copy()
    others  = pivot.drop(columns=top_groups, errors="ignore").sum(axis=1)
    plot_df["기타"] = others

    fig, ax = plt.subplots(figsize=(14, 5))
    colors = plt.cm.tab10(np.linspace(0, 1, len(plot_df.columns)))

    bottom_pos = np.zeros(len(plot_df))
    bottom_neg = np.zeros(len(plot_df))
    x = np.arange(len(plot_df))

    for i, col in enumerate(plot_df.columns):
        vals = plot_df[col].values
        pos  = np.where(vals >= 0, vals, 0)
        neg  = np.where(vals <  0, vals, 0)
        ax.bar(x, pos, bottom=bottom_pos, label=col, color=colors[i], width=0.8)
        ax.bar(x, neg, bottom=bottom_neg, color=colors[i], width=0.8)
        bottom_pos += pos
        bottom_neg += neg

    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(x[::6])
    ax.set_xticklabels(plot_df.index[::6], rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("YoY Δ계정수")
    ax.set_title(f"{target} — [{seg_col}] 월별 기여 추이 (YoY)", fontsize=12)
    ax.legend(loc="upper left", fontsize=8, ncol=2)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))

    plt.tight_layout()
    path = os.path.join(OUT_DIR, f"monthly_{target}_{seg_col}.png")
    plt.savefig(path, dpi=130); plt.close()
    print(f"  저장: {path}")


def plot_col_ranking(col_rank: pd.DataFrame, target: str):
    """세그먼트 컬럼별 top-1 그룹 기여도 비교 차트. 구조적 지배는 회색으로 구분."""
    os.makedirs(OUT_DIR, exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 6))
    y = np.arange(len(col_rank))

    colors = [
        "#cccccc" if r["is_dominated"] else "#E63946"
        for _, r in col_rank.iterrows()
    ]
    bars = ax.barh(y, col_rank["top1_share_pct"], color=colors)
    ax.axvline(DOMINANCE_THRESHOLD, color="#999", linewidth=1.2,
               linestyle="--", label=f"구조적 지배 기준 ({DOMINANCE_THRESHOLD}%)")

    labels = []
    for _, r in col_rank.iterrows():
        tag = "  [구조적]" if r["is_dominated"] else ""
        labels.append(f"{r['seg_col']}  [{r['top1_group']}]{tag}")
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=10)
    ax.set_xlabel("Top-1 그룹의 |Δ| 비중 (%)")
    ax.set_title(f"{target} — 세그먼트 컬럼별 최대 기여 그룹\n(회색=구조적 지배, 빨강=실질 분석 대상)", fontsize=11)
    ax.legend(fontsize=9)
    plt.tight_layout()
    path = os.path.join(OUT_DIR, f"col_ranking_{target}.png")
    plt.savefig(path, dpi=130); plt.close()
    print(f"  저장: {path}")


# ── 메인 ─────────────────────────────────────────────────────
def run(target: str):
    print(f"\n{'='*60}")
    print(f"target={target}")
    print(f"{'='*60}")

    # 1) 세그먼트 컬럼별 랭킹
    print("세그먼트 컬럼별 기여도 분석 중...")
    col_rank = rank_segment_cols(target)

    dominated = col_rank[col_rank["is_dominated"]]
    meaningful = col_rank[~col_rank["is_dominated"] & (col_rank["top1_corr"] >= MIN_CORR)]

    print(f"\n  [구조적 지배 — 분석 의미 낮음 (비중 {DOMINANCE_THRESHOLD}% 이상)]")
    print(f"  {'컬럼':<16} {'Top1 그룹':<20} {'비중(%)':>8}")
    print("  " + "-"*48)
    for _, r in dominated.iterrows():
        print(f"  {r['seg_col']:<16} {str(r['top1_group']):<20} {r['top1_share_pct']:>8.1f}")

    print(f"\n  [실질 분석 대상 — 변화를 주도하는 세그먼트]")
    print(f"  {'컬럼':<16} {'Top1 그룹':<20} {'비중(%)':>8} {'상관':>7} {'평균|Δ|':>10}")
    print("  " + "-"*65)
    for _, r in meaningful.iterrows():
        print(f"  {r['seg_col']:<16} {str(r['top1_group']):<20} "
              f"{r['top1_share_pct']:>8.1f} {r['top1_corr']:>7.3f} {r['top1_mean_abs']:>10.1f}")

    # 2) 실질 분석 대상 컬럼만 상세 분석 (상위 3개)
    focus_cols = meaningful.head(3)["seg_col"].tolist()
    if not focus_cols:
        print("\n  ⚠ 실질 분석 대상 컬럼 없음 — DOMINANCE_THRESHOLD를 높여보세요")
        focus_cols = col_rank.head(2)["seg_col"].tolist()

    for seg_col in focus_cols:
        print(f"\n[{seg_col}] 상세 분석")
        pivot   = build_monthly_delta(target, seg_col)
        contrib = compute_contribution(pivot)

        # 그룹 단위 필터: 비중 80% 미만 그룹만 표시
        meaningful_groups = contrib[contrib["share_pct"] < DOMINANCE_THRESHOLD]

        print(f"  {'그룹':<20} {'비중(%)':>8} {'평균|Δ|':>10} {'상관':>7} {'방향':>8}")
        print("  " + "-"*58)
        for _, r in meaningful_groups.head(8).iterrows():
            dir_str  = f"{r['mean_direction']:+.1f}"
            corr_tag = "  ← 주목" if r["corr_with_total"] >= 0.7 and r["share_pct"] >= 20 else ""
            print(f"  {str(r['group']):<20} {r['share_pct']:>8.1f} "
                  f"{r['mean_abs_delta']:>10.1f} {r['corr_with_total']:>7.3f} {dir_str:>8}{corr_tag}")

        path_csv = os.path.join(OUT_DIR, f"summary_{target}_{seg_col}.csv")
        os.makedirs(OUT_DIR, exist_ok=True)
        contrib.to_csv(path_csv, index=False, encoding="utf-8-sig")

        plot_ranking(meaningful_groups.reset_index(drop=True), target, seg_col)
        plot_monthly_stacked(pivot, meaningful_groups.reset_index(drop=True), target, seg_col)

    # 3) 컬럼별 비교 차트
    plot_col_ranking(col_rank, target)

    # 4) 핵심 인사이트 요약
    print(f"\n{'─'*60}")
    print(f"  핵심 인사이트 — {target}")
    print(f"{'─'*60}")
    for _, r in meaningful.head(3).iterrows():
        direction = "증가" if r["top1_corr"] > 0 else "감소"
        print(f"  • [{r['seg_col']}] {r['top1_group']} 그룹이 전체 변화의 "
              f"{r['top1_share_pct']:.0f}% 주도 (상관 {r['top1_corr']:.2f})")

    return col_rank


# ── 특정 월 분석 ───────────────────────────────────────────────
def analyze_month(target: str, year_month: str):
    """
    특정 월을 선택하면 전달(MoM) / 전년동월(YoY) 대비
    세그먼트별 기여도를 자동으로 계산해 출력.

    Parameters
    ----------
    target     : "신규" | "해지"
    year_month : "YYYY.MM" 형식  (예: "2024.03")

    출력
    ----
    - 전체 계정수 변화량 (MoM / YoY)
    - 세그먼트 컬럼별 그룹 기여 테이블
    - contribution_outputs/month_{target}_{year_month}.png 차트
    """
    prev_month = _shift_month(year_month, -1)    # 전달
    yoy_month  = _shift_month(year_month, -12)   # 전년 동월

    df = load_raw(target)
    available = set(df["년월"].unique())
    for m, label in [(year_month, "선택 월"), (prev_month, "전달"), (yoy_month, "전년동월")]:
        if m not in available:
            print(f"  ⚠ {label}({m}) 데이터 없음")
            return

    def month_total(m):
        return df[df["년월"] == m]["계정수"].sum()

    cur_total  = month_total(year_month)
    prev_total = month_total(prev_month)
    yoy_total_ = month_total(yoy_month)

    mom_total = cur_total - prev_total
    yoy_total = cur_total - yoy_total_

    print(f"\n{'='*62}")
    print(f"  {target}  —  {year_month} 월 분석")
    print(f"  전달 대비   (MoM): {prev_month} → {year_month}   {mom_total:+,.0f} 계정")
    print(f"  전년동월 대비(YoY): {yoy_month} → {year_month}   {yoy_total:+,.0f} 계정")
    print(f"{'='*62}")

    cols = list(SEGMENT_COLS)
    if target == "해지":
        cols = cols + [CANCEL_EXTRA_COL]

    all_results = {}

    for col in cols:
        agg = (
            df.groupby([col, "년월"], observed=True)["계정수"]
            .sum().reset_index()
        )
        def grp_count(m):
            return agg[agg["년월"] == m].set_index(col)["계정수"]

        cur  = grp_count(year_month)
        prev = grp_count(prev_month)
        yoy  = grp_count(yoy_month)
        all_grp = cur.index.union(prev.index).union(yoy.index)

        cur  = cur.reindex(all_grp).fillna(0)
        prev = prev.reindex(all_grp).fillna(0)
        yoy  = yoy.reindex(all_grp).fillna(0)

        mom_d = cur - prev
        yoy_d = cur - yoy

        mom_abs_sum = mom_d.abs().sum()
        yoy_abs_sum = yoy_d.abs().sum()
        mom_share = (mom_d.abs() / mom_abs_sum * 100) if mom_abs_sum > 0 else mom_d * 0
        yoy_share = (yoy_d.abs() / yoy_abs_sum * 100) if yoy_abs_sum > 0 else yoy_d * 0

        col_df = pd.DataFrame({
            "group":     all_grp,
            "mom_delta": mom_d.values,
            "mom_share": mom_share.values.round(1),
            "yoy_delta": yoy_d.values,
            "yoy_share": yoy_share.values.round(1),
        }).sort_values("yoy_share", ascending=False).reset_index(drop=True)

        # 구조적 지배 필터 (비중 80% 이상 제외)
        col_df["is_dominated"] = col_df["yoy_share"] >= DOMINANCE_THRESHOLD
        meaningful = col_df[~col_df["is_dominated"]].head(6)

        if meaningful.empty:
            continue

        all_results[col] = col_df

        print(f"\n  [{col}]")
        print(f"  {'그룹':<20} {'YoY Δ':>9} {'YoY비중':>7}  {'MoM Δ':>9} {'MoM비중':>7}")
        print("  " + "─" * 58)
        for _, r in meaningful.iterrows():
            flag = "  ★" if abs(r["yoy_share"]) >= 20 and r["yoy_delta"] != 0 else ""
            print(f"  {str(r['group']):<20} {r['yoy_delta']:>+9.0f} {r['yoy_share']:>6.1f}%"
                  f"  {r['mom_delta']:>+9.0f} {r['mom_share']:>6.1f}%{flag}")

    # ── 차트 (YoY 기준 상위 컬럼들) ──────────────────────────────
    _plot_month_chart(all_results, target, year_month, mom_total, yoy_total)
    return all_results


def _plot_month_chart(results: dict, target: str, year_month: str,
                       mom_total: float, yoy_total: float):
    """analyze_month 결과를 막대 차트로 시각화."""
    os.makedirs(OUT_DIR, exist_ok=True)

    # 상위 컬럼 최대 4개만
    cols = list(results.keys())[:4]
    if not cols:
        return

    fig, axes = plt.subplots(1, len(cols), figsize=(5 * len(cols), 5))
    if len(cols) == 1:
        axes = [axes]

    fig.suptitle(
        f"{target}  —  {year_month} 분석\n"
        f"YoY {yoy_total:+,.0f}계정  /  MoM {mom_total:+,.0f}계정",
        fontsize=12, fontweight="bold"
    )

    for ax, col in zip(axes, cols):
        df = results[col].copy()
        df = df[~df["is_dominated"]].head(8)
        colors = ["#E74C3C" if v < 0 else "#3498DB" for v in df["yoy_delta"]]
        ax.barh(df["group"][::-1], df["yoy_delta"][::-1], color=colors[::-1])
        ax.axvline(0, color="black", linewidth=0.8)
        ax.set_title(col, fontsize=10)
        ax.set_xlabel("YoY Δ 계정수")
        ax.xaxis.set_major_formatter(
            plt.FuncFormatter(lambda v, _: f"{int(v):+,}")
        )

    plt.tight_layout()
    path = os.path.join(OUT_DIR, f"month_{target}_{year_month.replace('.','')}.png")
    plt.savefig(path, dpi=130)
    plt.close()
    print(f"\n  차트 저장: {path}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="세그먼트 기여도 분석")
    parser.add_argument("--month",  type=str, default=None,
                        help="특정 월 분석 (예: 2024.03). 미지정 시 전체 트렌드 분석.")
    parser.add_argument("--target", type=str, default=None,
                        help="신규 | 해지. 미지정 시 둘 다 실행.")
    args = parser.parse_args()

    targets = [args.target] if args.target else ["신규", "해지"]

    if args.month:
        # ── 특정 월 분석 모드 ──
        for t in targets:
            analyze_month(t, args.month)
        print("\n완료.")
    else:
        # ── 전체 트렌드 분석 모드 ──
        for t in targets:
            run(t)
        print("\n완료. contribution_outputs/ 폴더에 결과 저장됨")
