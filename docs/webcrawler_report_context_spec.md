# WebCrawler 시장 관측 자료 생성 명세

## 목적

역할은 정수기 구독 시장 관련 웹 데이터를 수집하고, LLM이 최종 리포트를 만들 수 있도록 정제된 시장 관측 자료를 생성하는 것이다.

현재 파이프라인은 다음과 같다.

```text
크롤링 -> 원본 저장 -> LLM 전처리/요약 -> AI 보고서 생성기에 넣을 요약 정보
```

최종 산출물은 리포트 생성 LLM에 넣을 JSON이다.

## 처리 범위

수집 대상은 `PythonCode/WebCrawler/targets.yaml` 기준으로 관리한다.

현재 활성 소스는 다음 3개다.

| source_id | 내용 | 저장 테이블 |
| --- | --- | --- |
| `naver_news` | 네이버 뉴스 검색 결과와 기사 본문 | `raw_documents` |
| `naver_blog` | 네이버 블로그 검색 결과와 본문 | `raw_documents` |
| `naver_shopping` | 네이버 쇼핑 상품 후보와 가격 스냅샷 | `product_snapshots` |

## 주요 모듈

| 파일 | 책임 |
| --- | --- |
| `PythonCode/WebCrawler/cli.py` | 명령어 진입점과 argparse 처리 |
| `PythonCode/WebCrawler/crawler_service.py` | 뉴스/블로그/쇼핑 크롤링 실행과 crawl-all orchestration |
| `PythonCode/WebCrawler/query_builder.py` | `targets.yaml` 기반 검색 query 생성 |
| `PythonCode/WebCrawler/sources/naver_news.py` | 네이버 뉴스 API 호출과 뉴스 item 정규화 |
| `PythonCode/WebCrawler/sources/article_fetcher.py` | 뉴스 본문 HTML fetch 및 텍스트 추출 |
| `PythonCode/WebCrawler/sources/naver_blog.py` | 네이버 블로그 API 호출과 블로그 item 정규화 |
| `PythonCode/WebCrawler/sources/naver_blog_fetcher.py` | 블로그 본문 fetch 및 텍스트 추출 |
| `PythonCode/WebCrawler/sources/naver_shopping.py` | 네이버 쇼핑 API 호출과 상품 item 정규화 |
| `PythonCode/WebCrawler/storage/duckdb_store.py` | DuckDB upsert 및 hash/url 정규화 |
| `PythonCode/WebCrawler/storage/raw_store.py` | raw JSON/TXT 파일 저장 |
| `PythonCode/WebCrawler/summarizer.py` | 기사/블로그 LLM 요약 전처리 |
| `PythonCode/WebCrawler/market_relevance.py` | 정수기 시장 관련성 필터 |
| `PythonCode/WebCrawler/exporters/issue_exporter.py` | raw 문서와 summary 문서 export helper |
| `PythonCode/WebCrawler/exporters/shopping_exporter.py` | 쇼핑 가격/상품 변화 집계 |
| `PythonCode/WebCrawler/exporters/report_context_exporter.py` | LLM용 시장 관측 context JSON 생성 |

## 저장 구조

런타임 데이터는 `WebCrawlDB` 아래에 둔다.

```text
WebCrawlDB/
  raw/                 # 크롤링 원본 JSON/TXT
  warehouse/
    market.duckdb      # DuckDB 저장소
  exports/             # export JSON 산출물
  schema.sql           # DuckDB schema
```

## DB 스키마

### raw_documents

뉴스/블로그 원본 문서 단위 저장소다.

주요 컬럼:

| 컬럼 | 설명 |
| --- | --- |
| `doc_id` | 문서 ID |
| `source_id` | `naver_news`, `naver_blog` |
| `query` | 수집에 사용한 검색어 |
| `brand_id`, `brand_name` | 브랜드 매핑 |
| `title`, `url` | 제목과 원문 URL |
| `published_at`, `crawled_at` | 발행/수집 시각 |
| `raw_path` | raw JSON 파일 경로 |
| `text_path` | LLM/이슈 추출용 TXT 경로 |
| `content_hash`, `url_hash` | 캐시/중복 제거 키 |
| `metadata_json` | API 응답, 본문 추출 상태 등 부가 정보 |

현재는 JSON과 TXT를 같이 저장한다. 장기적으로는 JSON 안에 `llm_source_text`를 포함시키고 `text_path`를 제거하는 리팩터가 가능하다.

### product_snapshots

쇼핑 상품 가격 스냅샷 저장소다.

주요 컬럼:

| 컬럼 | 설명 |
| --- | --- |
| `snapshot_id` | 스냅샷 ID |
| `brand_id`, `brand_name` | 브랜드 |
| `product_name`, `model_code`, `category` | 상품 식별 정보 |
| `sales_type` | `rental` 또는 구매형 |
| `purchase_price`, `rental_fee` | 구매가/렌탈료 |
| `captured_date`, `captured_at` | 관측 날짜/시각 |
| `product_url` | 상품 식별용 URL |
| `raw_path`, `content_hash`, `metadata_json` | 원본/메타데이터 |

최종 report context에는 전체 상품 목록, URL, 이미지 URL, mall name을 내보내지 않는다. 가격 변화, 신규 관측, 관측 제외 이벤트만 사용한다.

### document_summaries

뉴스/블로그 문서를 LLM으로 전처리한 결과 저장소다.

주요 컬럼:

| 컬럼 | 설명 |
| --- | --- |
| `summary_id` | 요약 ID |
| `doc_id`, `content_hash` | 원문 문서 캐시 키 |
| `source_id` | `naver_news`, `naver_blog` |
| `brand_id`, `brand_name` | 브랜드 |
| `is_relevant` | 정수기 시장 관련 여부 |
| `summary` | 한 문장 요약 |
| `key_points_json` | 리포트 작성용 근거 사실 |
| `evidence_excerpt` | 짧은 원문 근거 |
| `mentioned_products_json` | 확인된 정수기 제품명 |
| `confidence` | 0.0~1.0 신뢰도 |
| `model_name`, `prompt_version` | LLM 캐시 키 |
| `metadata_json` | event type, sentiment, provider 등 |

unique index:

```text
doc_id + content_hash + model_name + prompt_version
```

같은 원문, 같은 모델, 같은 prompt version은 재요약하지 않는다. `--force`를 쓰면 강제로 재생성한다.

## LLM 전처리

명령어:

```powershell
python -m PythonCode.WebCrawler.cli summarize-documents --month 2026-06
```

역할:

1. `raw_documents`에서 해당 월 뉴스/블로그 문서를 읽는다.
2. `text_path`의 본문을 요약 입력으로 만든다.
3. LLM에 JSON 구조로 요약을 요청한다.
4. 정수기 시장 관련성 필터를 한 번 더 적용한다.
5. `document_summaries`에 upsert한다.

LLM 출력 스키마:

```json
{
  "is_relevant": true,
  "event_type": "consumer_reaction",
  "summary": "한 문장 요약",
  "key_points": ["근거 사실"],
  "evidence_excerpt": "짧은 근거",
  "mentioned_products": [],
  "sentiment": "neutral",
  "confidence": 0.75
}
```

허용 event type:

```text
new_product
price_promotion
marketing_campaign
negative_issue
consumer_reaction
corporate_strategy
general_market_reaction
```

관련성 필터 기준:

- 정수기 시장과 무관하면 `is_relevant=false`
- 브랜드명이나 검색 query만으로 관련 문서로 보지 않음
- 음식물처리기, 비데, 공기청정기, 인덕션 등 타제품 중심 문서는 제외
- 정수기가 배경으로만 언급되고 실제 사건이 타제품이면 제외
- `facts`, `mentioned_products`에서도 정수기 아닌 항목은 제거

## 환경 변수

필수 또는 주요 변수:

```env
NAVER_API_CLIENT_ID=
NAVER_API_CLIENT_SECRET=

OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
WEBCRAWLER_SUMMARY_MODEL=gpt-4.1-mini

AZURE_OAI_ENDPOINT=
AZURE_OAI_KEY=
AZURE_OAI_DEPLOYMENT=
```

모델 선택 우선순위:

1. `WEBCRAWLER_SUMMARY_MODEL`
2. `OPENAI_MODEL`
3. 기본값 `gpt-4o-mini`

현재 요약 모델:

```env
WEBCRAWLER_SUMMARY_MODEL=gpt-4.1-mini
```

## CLI 사용법

가상환경 활성화:

```powershell
.\.venv\Scripts\Activate.ps1
```

DB 초기화:

```powershell
python -m PythonCode.WebCrawler.cli init-db
```

전체 크롤링:

```powershell
python -m PythonCode.WebCrawler.cli crawl-all --fetch-article --fetch-blog-body
```

권장 테스트 수집:

```powershell
python -m PythonCode.WebCrawler.cli crawl-all `
  --fetch-article `
  --fetch-blog-body `
  --news-limit-queries 0 `
  --news-display 20 `
  --article-limit-per-query 5 `
  --blog-limit-queries 0 `
  --blog-display 20 `
  --blog-body-limit-per-query 5 `
  --shopping-display 80 `
  --max-products 40
```

문서 요약:

```powershell
python -m PythonCode.WebCrawler.cli summarize-documents --month 2026-06
```

특정 source만 요약:

```powershell
python -m PythonCode.WebCrawler.cli summarize-documents --month 2026-06 --source naver_news
python -m PythonCode.WebCrawler.cli summarize-documents --month 2026-06 --source naver_blog
```

강제 재요약:

```powershell
python -m PythonCode.WebCrawler.cli summarize-documents --month 2026-06 --force
```

LLM용 report context export:

```powershell
python -m PythonCode.WebCrawler.cli export-report-context --month 2026-06
```

출력 경로:

```text
WebCrawlDB/exports/report_context_2026-06_all.json
```

## report context 산출물

dataset:

```text
market_observation_material
```

최상위 구조:

```json
{
  "generated_at": "...",
  "period": {
    "month": "2026-06",
    "from": "2026-06-01",
    "to": "2026-07-01"
  },
  "source": "web_crawler",
  "dataset": "market_observation_material",
  "filters": {},
  "stats": {},
  "context": {
    "market_summary": {},
    "events": [],
    "shopping": {},
    "source_refs": {}
  }
}
```

`context.events`는 뉴스/블로그 LLM 요약 이벤트와 쇼핑 변화 이벤트를 합친 목록이다.

이벤트 예시:

```json
{
  "event_id": "summary_xxx",
  "event_date": "2026-06-25",
  "event_type": "price_promotion",
  "material_source": "naver_news",
  "brand_id": "coway",
  "brand_name": "코웨이",
  "title": "...",
  "summary": "...",
  "facts": ["..."],
  "mentioned_products": ["..."],
  "sentiment": "neutral",
  "confidence": 0.82,
  "source_ref": {
    "doc_id": "...",
    "summary_id": "...",
    "source_id": "naver_news",
    "summary_model": "gpt-4.1-mini",
    "prompt_version": "webcrawler_document_summary_v2"
  }
}
```

쇼핑 이벤트는 다음 경우에 생성한다.

- 가격 하락
- 가격 상승
- 신규 관측 상품
- 이전 관측 대비 사라진 상품

가격 변화 이벤트는 최소 2개 이상의 `captured_date`가 있어야 의미 있게 생성된다.

## export 정책

report context에는 다음을 넣지 않는다.

- 전체 최신 상품 목록
- 상품 URL
- 이미지 URL
- mall name
- raw 본문 전체
- 최종 리포트 문장

report context는 LLM 입력 자료이므로 다음만 포함한다.

- 월간 시장 이벤트
- 이벤트별 요약
- 근거 fact
- 관련 제품명
- 브랜드/소스별 count
- 쇼핑 가격 변화 요약
- 데이터 한계 사항

`document_summaries`가 없으면 raw heuristic fallback을 사용하지 않는다. 대신 `limitations`에 `summarize-documents`를 먼저 실행하라는 안내를 남긴다.

## Python 코드에서 직접 호출

CLI 외부에서도 함수 호출이 가능하다.

```python
from pathlib import Path

from PythonCode.WebCrawler.config import DUCKDB_PATH, SCHEMA_PATH, load_targets
from PythonCode.WebCrawler.crawler_service import crawl_all
from PythonCode.WebCrawler.storage.duckdb_store import init_db
from PythonCode.WebCrawler.summarizer import summarize_documents
from PythonCode.WebCrawler.exporters.report_context_exporter import (
    export_report_context,
)

init_db(DUCKDB_PATH, SCHEMA_PATH)

targets = load_targets(Path("PythonCode/WebCrawler/targets.yaml"))
crawl_all(
    targets,
    fetch_article=True,
    fetch_blog_body=True,
)

stats = summarize_documents(
    DUCKDB_PATH,
    month="2026-06",
)

package = export_report_context(
    DUCKDB_PATH,
    month="2026-06",
)
```


## 현재 한계와 후속 작업

1. JSON/TXT 이중 저장
   - 현재는 `raw_path`와 `text_path`를 모두 저장한다.
   - 장기적으로 raw JSON 안에 `llm_source_text`를 포함시키면 `text_path`를 제거할 수 있다.

2. Batch API
   - 현재 요약은 문서별 실시간 LLM 호출이다.
   - 월별 대량 문서 요약은 batch input 생성, batch 제출, batch 결과 import 구조로 확장할 수 있다.

3. 쇼핑 관측 품질
   - 가격 변화/신규/소멸 이벤트는 같은 상품을 여러 날짜에 관측해야 정확하다.
   - 쇼핑은 하루 대량 수집보다 매일 또는 격일 반복 수집이 중요하다.
