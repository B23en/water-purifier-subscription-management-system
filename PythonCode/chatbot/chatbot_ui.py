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
            # ✅ Azure API 호출
            result = parse_query(user_input)

            # ✅ API 상태 저장
            st.session_state["api_success"] = True
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

            st.session_state["chat_history"].insert(0, {
                "question": user_input,
                "status": "실패"
            })
            st.session_state["chat_history"] = st.session_state["chat_history"][:5]

            st.sidebar.error(f"에러 발생: {e}")
