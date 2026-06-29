"""
[Dashboard] 시장동향 (웹크롤러 report_context 시각화)
================================================================
- WebCrawler 파이프라인이 export 한 report_context_{YYYY-MM}_all.json 을 읽어
  시장 관측 자료(뉴스/블로그 LLM 요약 이벤트 + 쇼핑 가격 요약)를 시각화한다.
- 크롤링/요약/export 는 오프라인(CLI)에서 수행 — 이 화면은 '결과만' 표시한다.
  데이터가 없으면 실행 방법을 안내한다.
"""
import json
import re
from pathlib import Path

import streamlit as st

_FNAME_RE = re.compile(r"report_context_(\d{4}-\d{2})_.+\.json$")

EVENT_TYPE_KR = {
    "new_product": "신제품",
    "price_promotion": "가격/프로모션",
    "marketing_campaign": "마케팅",
    "negative_issue": "부정이슈",
    "consumer_reaction": "소비자반응",
    "corporate_strategy": "기업전략",
    "general_market_reaction": "일반시장반응",
}
SENTIMENT_KR = {"positive": "긍정", "neutral": "중립", "negative": "부정"}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _exports_dir() -> Path:
    return _repo_root() / "WebCrawlDB" / "exports"


def _available_exports():
    """{month: path} (최신월 우선)."""
    out = {}
    d = _exports_dir()
    if d.exists():
        for p in d.glob("report_context_*_*.json"):
            m = _FNAME_RE.search(p.name)
            if m:
                out[m.group(1)] = p
    return dict(sorted(out.items(), reverse=True))


def _guidance():
    st.info(
        "아직 크롤링 데이터가 없습니다. 아래 명령으로 수집 → 요약 → export 를 먼저 실행하세요.\n"
        "(네이버/OpenAI 키는 PythonCode/.env 에 설정)"
    )
    st.code(
        "python -m PythonCode.WebCrawler.cli init-db\n"
        "python -m PythonCode.WebCrawler.cli crawl-all --fetch-article --fetch-blog-body\n"
        "python -m PythonCode.WebCrawler.cli summarize-documents --month 2026-06\n"
        "python -m PythonCode.WebCrawler.cli export-report-context --month 2026-06",
        language="bash",
    )


def _render_events(events):
    st.markdown("### 📰 시장 이벤트")
    if not events:
        st.caption("표시할 시장 이벤트가 없습니다.")
        return
    for ev in events:
        etype = EVENT_TYPE_KR.get(ev.get("event_type"), ev.get("event_type") or "")
        src = "뉴스" if ev.get("material_source") == "naver_news" else "블로그"
        conf = ev.get("confidence")
        title = ev.get("title") or "(제목 없음)"
        with st.expander(f"[{src}] {title}"):
            meta = (
                f"**브랜드** {ev.get('brand_name') or '-'}  ·  "
                f"**유형** {etype}  ·  "
                f"**감성** {SENTIMENT_KR.get(ev.get('sentiment'), ev.get('sentiment') or '-')}  ·  "
                f"**신뢰도** {conf if conf is not None else '-'}  ·  "
                f"**일자** {ev.get('event_date') or '-'}"
            )
            st.markdown(meta)
            if ev.get("summary"):
                st.markdown(f"> {ev['summary']}")
            facts = ev.get("facts") or []
            if facts:
                st.markdown("**근거 사실**")
                for f in facts:
                    st.markdown(f"- {f}")
            prods = ev.get("mentioned_products") or []
            if prods:
                st.caption("언급 제품: " + ", ".join(map(str, prods)))
            url = ev.get("url")
            if url:
                st.markdown(f"🔗 [원문 보기]({url})")


def _render_shopping(shopping):
    ps = (shopping or {}).get("price_summary") or {}
    if not ps:
        return
    st.markdown("### 🛒 쇼핑 가격 요약")

    def _won(x):
        return f"{int(x):,}원" if isinstance(x, (int, float)) else "-"

    pur = ps.get("purchase_price") or {}
    ren = ps.get("rental_fee") or {}
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**구매형**")
        st.caption(f"관측 {pur.get('count', 0)}건")
        st.write(f"최저 {_won(pur.get('min'))} · 평균 {_won(pur.get('avg'))} · 최고 {_won(pur.get('max'))}")
    with c2:
        st.markdown("**렌탈형(월)**")
        st.caption(f"관측 {ren.get('count', 0)}건")
        st.write(f"최저 {_won(ren.get('min'))} · 평균 {_won(ren.get('avg'))} · 최고 {_won(ren.get('max'))}")

    # 가격 변화 이벤트(여러 관측일이 쌓여야 생성됨)
    cap_dates = (shopping.get("stats") or {}).get("captured_dates") or []
    if len(cap_dates) < 2:
        st.caption("※ 가격 변화 추적은 2개 이상의 관측일이 필요합니다 (현재 관측일 "
                   f"{len(cap_dates)}일). 매일/격일 반복 수집 시 가격 하락·상승·신규·소멸 이벤트가 생성됩니다.")


def render_dashboard(context: dict):
    st.markdown("## 🌐 시장동향 (웹크롤링)")
    st.caption("정수기 시장 뉴스·블로그 LLM 요약 + 쇼핑 가격 관측 (웹크롤러 export 결과)")

    exports = _available_exports()
    if not exports:
        _guidance()
        return

    # 월 선택 (기본: 최신)
    months = list(exports.keys())
    month = st.selectbox("기준월", months, index=0, key="market_month")
    try:
        data = json.loads(exports[month].read_text(encoding="utf-8"))
    except Exception as e:
        st.error(f"export 파일을 읽지 못했습니다: {e}")
        return

    stats = data.get("stats", {})
    ctx = data.get("context", {})
    ms = ctx.get("market_summary", {})

    st.caption(
        f"수집 기간 {data.get('period', {}).get('from')} ~ {data.get('period', {}).get('to')} · "
        f"생성 {data.get('generated_at')}"
    )

    # 요약 지표
    c = st.columns(5)
    c[0].metric("시장 이벤트", stats.get("market_event_count", 0))
    c[1].metric("뉴스 요약", stats.get("news_summary_count", 0))
    c[2].metric("블로그 요약", stats.get("blog_summary_count", 0))
    c[3].metric("쇼핑 스냅샷", stats.get("shopping_snapshot_count", 0))
    c[4].metric("브랜드 수", stats.get("shopping_brand_count", 0))

    st.markdown("---")
    _render_events(ctx.get("events", []))
    st.markdown("---")
    _render_shopping(ctx.get("shopping", {}))

    # 데이터 한계 안내
    lims = ms.get("limitations") or []
    if lims:
        with st.expander("데이터 한계 / 안내"):
            for l in lims:
                st.markdown(f"- {l}")
