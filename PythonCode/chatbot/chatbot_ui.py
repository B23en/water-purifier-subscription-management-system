import streamlit as st
from chatbot.llm_parser import parse_query
from chatbot.intent_router import apply_intent


# 사이드바에 노출할 예시 질문 템플릿 (클릭 시 입력창에 채우고 바로 분석)
EXAMPLE_QUESTIONS = [
    "이번달 신규 예측해줘",
    "저저번달 신규 왜 줄었어",
    "해지 다음달 전망",
    "재구독률 예상치",
    "지난달 해지 증가 원인",
    "최근 6개월 신규 채널별 판매",
]


def _process(user_input, dashboard_registry):
    """질의 1건 처리: 파싱 → 상태/이력 저장 → 대시보드 이동."""
    try:
        # ✅ 챗봇 질의 파싱 (OpenAI > Azure > 키워드 fallback)
        result = parse_query(user_input)

        # ✅ 실제 사용된 경로(openai/azure/fallback)를 상태로 저장
        provider = result.get("provider", "fallback")
        st.session_state["llm_provider"] = provider
        st.session_state["api_success"] = provider in ("openai", "azure")
        st.session_state["api_result"] = result

        # ✅ 이력 저장 (최근 5개)
        st.session_state["chat_history"].insert(0, {
            "question": user_input,
            "status": "성공",
        })
        st.session_state["chat_history"] = st.session_state["chat_history"][:5]

        # ✅ Dashboard 이동
        apply_intent(result, dashboard_registry)

    except Exception as e:
        st.session_state["api_success"] = False
        st.session_state["llm_provider"] = None

        st.session_state["chat_history"].insert(0, {
            "question": user_input,
            "status": "실패",
        })
        st.session_state["chat_history"] = st.session_state["chat_history"][:5]

        st.sidebar.error(f"에러 발생: {e}")


def render_chatbot(dashboard_registry):

    st.sidebar.markdown("💬 실적 챗봇")

    # -----------------------------------------
    # 예시 질문 템플릿 (클릭 → 입력창 채우고 바로 분석)
    # -----------------------------------------
    st.sidebar.caption("예시 질문 (클릭하면 바로 분석)")
    for i, ex in enumerate(EXAMPLE_QUESTIONS):
        if st.sidebar.button(ex, key=f"tmpl_{i}", use_container_width=True):
            # 위젯 생성 전에 입력값을 세팅해야 입력창에 반영됨
            st.session_state["chat_input"] = ex
            st.session_state["_chat_run"] = ex

    # -----------------------------------------
    # 직접 입력
    # -----------------------------------------
    user_input = st.sidebar.text_input("질문 입력", key="chat_input")

    if st.sidebar.button("분석"):
        st.session_state["_chat_run"] = user_input

    # -----------------------------------------
    # 실행 (템플릿 클릭 또는 분석 버튼)
    # -----------------------------------------
    run_text = st.session_state.pop("_chat_run", None)
    if run_text is not None:
        if not run_text.strip():
            st.sidebar.warning("질문을 입력해주세요.")
        else:
            _process(run_text, dashboard_registry)
