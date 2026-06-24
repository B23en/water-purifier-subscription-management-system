import streamlit as st
from chatbot.llm_parser import parse_query
from chatbot.intent_router import apply_intent


def render_chatbot(dashboard_registry):

    st.sidebar.markdown("💬 실적 챗봇")

    user_input = st.sidebar.text_input("질문 입력")

    if st.sidebar.button("분석"):

        if not user_input:
            st.sidebar.warning("질문을 입력해주세요.")
            return

        try:
            # ✅ 챗봇 질의 파싱 (OpenAI > Azure > 키워드 fallback)
            result = parse_query(user_input)

            # ✅ 실제 사용된 경로(openai/azure/fallback)를 상태로 저장
            provider = result.get("provider", "fallback")
            st.session_state["llm_provider"] = provider
            st.session_state["api_success"] = provider in ("openai", "azure")
            st.session_state["api_result"] = result

            # ✅ ✅ ✅ 이력 저장 (핵심)
            st.session_state["chat_history"].insert(0, {
                "question": user_input,
                "status": "성공"
            })
            st.session_state["chat_history"] = st.session_state["chat_history"][:5]

            # ✅ Dashboard 이동
            apply_intent(result, dashboard_registry)

        except Exception as e:
            # ✅ 실패 처리
            st.session_state["api_success"] = False
            st.session_state["llm_provider"] = None

            st.session_state["chat_history"].insert(0, {
                "question": user_input,
                "status": "실패"
            })
            st.session_state["chat_history"] = st.session_state["chat_history"][:5]

            st.sidebar.error(f"에러 발생: {e}")
