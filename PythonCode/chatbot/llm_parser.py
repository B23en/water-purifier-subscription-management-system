# chatbot/llm_parser.py

import os
import json
import re
from dotenv import load_dotenv
from openai import OpenAI, AzureOpenAI

load_dotenv()


# ==========================================================
# ✅ LLM Client 생성 (개인 OpenAI 키 우선, 없으면 Azure)
# ==========================================================
def get_llm_client():
    """
    우선순위
    1) OPENAI_API_KEY 가 있으면 일반 OpenAI 사용 (개인 키 / 개발 환경 권장)
       - 모델: OPENAI_MODEL (기본 gpt-4o-mini)
    2) AZURE_OAI_* 3종이 있으면 Azure OpenAI 사용 (운영 환경)
    3) 둘 다 없으면 (None, None, None) → 키워드 fallback

    반환: (client, model, provider)
    - OpenAI / AzureOpenAI 모두 client.chat.completions.create() 인터페이스 동일
    """
    # 1) 개인 OpenAI 키
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        try:
            client = OpenAI(api_key=openai_key)
            model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
            print(f"✅ OpenAI client 생성 성공 (model={model})")
            return client, model, "openai"
        except Exception as e:
            print("🚨 OpenAI client 생성 실패:", e)

    # 2) Azure OpenAI (운영)
    endpoint = os.getenv("AZURE_OAI_ENDPOINT")
    azure_key = os.getenv("AZURE_OAI_KEY")
    deployment = os.getenv("AZURE_OAI_DEPLOYMENT")
    if endpoint and azure_key and deployment:
        try:
            client = AzureOpenAI(
                api_key=azure_key,
                azure_endpoint=endpoint,
                api_version="2024-02-15-preview",
            )
            print("✅ Azure client 생성 성공")
            return client, deployment, "azure"
        except Exception as e:
            print("🚨 Azure client 생성 실패:", e)

    print("🚨 사용 가능한 LLM 키 없음 → fallback")
    return None, None, None


# ==========================================================
# ✅ 기간 추출 보조 함수
# ==========================================================
def extract_month_candidates(text: str):
    """
    문자열에서 YYYY.MM / YYYY-MM / YY.MM / YY-MM / YYYY년 M월 / YY년 M월 등을 추출
    반환: ["2025.01", "2026.05"] 형태
    """
    results = []

    # 2025.01 / 2025-01 / 25.01 / 25-01
    p1 = re.findall(r'(?<!\d)((?:20)?\d{2})[.\- ](\d{1,2})(?!\d)', text)

    # 2025년 1월 / 25년 1월
    p2 = re.findall(r'(?<!\d)((?:20)?\d{2})\s*년\s*(\d{1,2})\s*월', text)

    for yy, mm in p1 + p2:
        yy = yy.strip()
        mm = int(mm)

        if len(yy) == 2:
            yy = "20" + yy

        if 1 <= mm <= 12:
            results.append(f"{yy}.{mm:02d}")

    # 중복 제거 (순서 유지)
    dedup = []
    for x in results:
        if x not in dedup:
            dedup.append(x)

    return dedup


def extract_period(user_input: str):
    """
    간단 기간 추출:
    - 2개 이상 잡히면 앞/뒤를 start/end
    - 1개만 잡히면:
      '부터' 있으면 start_month
      '까지' 있으면 end_month
      그 외는 start/end 둘 다 빈칸
    """
    months = extract_month_candidates(user_input)

    if len(months) >= 2:
        return months[0], months[1]

    if len(months) == 1:
        m = months[0]
        if "부터" in user_input:
            return m, ""
        elif "까지" in user_input:
            return "", m
        else:
            return "", ""

    return "", ""


# ==========================================================
# ✅ LLM 응답 후처리
# ==========================================================
def normalize_result(result: dict) -> dict:
    """
    누락 방지 / 허용값 정리
    """
    allowed_data_types = ["신규", "해지", "만기", "누적"]
    allowed_dashboards = ["채널", "방문주기", "계약유형", "누적계정현황", "미구축"]

    data_type = result.get("data_type", "")
    dashboard = result.get("dashboard", "")
    start_month = result.get("start_month", "")
    end_month = result.get("end_month", "")
    dashboard_supported = result.get("dashboard_supported", True)
    message = result.get("message", "")

    if data_type not in allowed_data_types:
        data_type = ""

    if dashboard not in allowed_dashboards:
        dashboard = ""

    if not isinstance(dashboard_supported, bool):
        dashboard_supported = True

    if message is None:
        message = ""

    return {
        "data_type": data_type,
        "dashboard": dashboard,
        "start_month": start_month,
        "end_month": end_month,
        "dashboard_supported": dashboard_supported,
        "message": message,
    }


# ==========================================================
# ✅ 메인 파서
# ==========================================================
def parse_query(user_input: str) -> dict:

    client, model, provider = get_llm_client()

    # ✅ CASE 1: 사용 가능한 키 없음
    if client is None:
        print("🚨 [FALLBACK] LLM client 없음")
        return fallback_parse(user_input)

    try:
        print(f"✅ [CASE2] LLM 호출 시작 (provider={provider})")

        prompt = f"""
반드시 아래 JSON 형식으로만 출력해라. 설명 금지. 코드블록 금지.

허용값:

data_type:
- 신규
- 해지
- 만기
- 누적

dashboard:
- 채널
- 방문주기
- 계약유형
- 누적계정현황
- 미구축

dashboard_supported:
- true
- false

규칙:
1. 질문에 신규/해지/만기/누적이 명시되면 그 값을 data_type으로 쓴다.
2. 신규/해지/만기/누적이 명시되지 않았을 때:
   - "판매"라는 단어가 있으면 data_type="신규"
   - 관련 단어가 없으면 data_type="누적"

3. 신규의 dashboard 규칙:
   - 판매채널/채널 -> dashboard="채널"
   - 방문주기/방문 -> dashboard="방문주기"
   - 계약유형/계약 -> dashboard="계약유형"
   - 아무 키워드가 없으면 dashboard="계약유형"
   - dashboard_supported=true

4. 해지/만기의 dashboard 규칙:
   - 계약유형/계약 또는 키워드가 없으면 dashboard="계약유형", dashboard_supported=true
   - 방문주기/방문 또는 판매채널/채널이면 dashboard="미구축", dashboard_supported=false, message="Dashboard 미구축"

5. 누적의 dashboard 규칙:
   - 키워드가 없으면 dashboard="누적계정현황", dashboard_supported=true
   - 계약유형/계약이면 dashboard="계약유형", dashboard_supported=true
   - 방문주기/방문 또는 판매채널/채널이면 dashboard="미구축", dashboard_supported=false, message="Dashboard 미구축"

6. 기간이 있으면 start_month, end_month에 YYYY.MM 형식으로 넣고, 없으면 빈 문자열로 둔다.
7. 반드시 JSON만 출력한다.

출력 형식:
{{
  "data_type": "",
  "dashboard": "",
  "start_month": "",
  "end_month": "",
  "dashboard_supported": true,
  "message": ""
}}

사용자 질문:
{user_input}
"""

        res = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )

        content = res.choices[0].message.content
        print("📌 응답 원문:", content)

        # ✅ JSON 추출
        json_match = re.search(r"\{.*\}", content, re.DOTALL)

        if json_match:
            json_str = json_match.group()
            result = json.loads(json_str)
            result = normalize_result(result)

            # ✅ 기간이 비었으면 fallback regex로 한 번 더 보강
            if not result["start_month"] and not result["end_month"]:
                s, e = extract_period(user_input)
                result["start_month"] = s
                result["end_month"] = e

            result["provider"] = provider
            print("✅ JSON 파싱 성공:", result)
            return result

        else:
            print("🚨 JSON 없음 → fallback")
            return fallback_parse(user_input)

    except Exception as e:
        print("🚨 [CASE2] API 실패 → fallback")
        print("에러:", e)
        return fallback_parse(user_input)


# ==========================================================
# ✅ fallback
# ==========================================================
def fallback_parse(user_input: str) -> dict:

    print("⚠️ [FALLBACK 실행됨]")

    text = user_input.lower()

    # ------------------------------------------
    # 기간 추출
    # ------------------------------------------
    start_month, end_month = extract_period(user_input)

    # ------------------------------------------
    # data_type 결정
    # ------------------------------------------
    if "신규" in text:
        data_type = "신규"
    elif "해지" in text:
        data_type = "해지"
    elif "만기" in text:
        data_type = "만기"
    elif "누적" in text:
        data_type = "누적"
    else:
        # ✅ 계정 관련 명시 없을 때
        if "판매" in text:
            data_type = "신규"
        else:
            data_type = "누적"

    # ------------------------------------------
    # dashboard 입력 키워드 추출
    # ------------------------------------------
    has_channel = ("채널" in text) or ("판매채널" in text)
    has_visit = ("방문" in text) or ("방문주기" in text)
    has_contract = ("계약" in text) or ("계약유형" in text)

    dashboard = ""
    dashboard_supported = True
    message = ""

    # ------------------------------------------
    # 신규
    # ------------------------------------------
    if data_type == "신규":
        if has_channel:
            dashboard = "채널"
        elif has_visit:
            dashboard = "방문주기"
        elif has_contract:
            dashboard = "계약유형"
        else:
            dashboard = "계약유형"

    # ------------------------------------------
    # 해지 / 만기
    # ------------------------------------------
    elif data_type in ["해지", "만기"]:
        if has_channel or has_visit:
            dashboard = "미구축"
            dashboard_supported = False
            message = "Dashboard 미구축"
        else:
            dashboard = "계약유형"

    # ------------------------------------------
    # 누적
    # ------------------------------------------
    elif data_type == "누적":
        if has_channel or has_visit:
            dashboard = "미구축"
            dashboard_supported = False
            message = "Dashboard 미구축"
        elif has_contract:
            dashboard = "계약유형"
        else:
            dashboard = "누적계정현황"

    result = {
        "data_type": data_type,
        "dashboard": dashboard,
        "start_month": start_month,
        "end_month": end_month,
        "dashboard_supported": dashboard_supported,
        "message": message,
        "mode": "fallback",
        "provider": "fallback",
    }

    print("✅ fallback 결과:", result)
    return result