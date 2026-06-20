import streamlit as st


def apply_intent(intent_data, dashboard_registry):

    if "error" in intent_data:
        st.warning("챗봇 해석 실패")
        return

    data_type = intent_data.get("data_type")
    dashboard_keyword = intent_data.get("dashboard", "")
    start_month = intent_data.get("start_month", "")
    end_month = intent_data.get("end_month", "")

    # -----------------------------
    # ✅ 탭 이동
    # -----------------------------
    if data_type in ["누적", "신규", "해지", "만기"]:
        st.session_state["selected_data_type"] = data_type
        st.session_state["force_tab_sync"] = True

    # -----------------------------
    # ✅ 기간 처리
    # -----------------------------
    today = st.session_state.get("latest_month", "2026.05")

    if start_month and not end_month:
        end_month = today

    elif end_month and not start_month:
        year = int(end_month.split(".")[0]) - 1
        start_month = f"{year}.01"

    elif not start_month and not end_month:
        year = int(today.split(".")[0]) - 1
        start_month = f"{year}.01"
        end_month = today

    # ✅ 적용
    if start_month:
        st.session_state[f"{data_type}_start_month"] = start_month

    if end_month:
        st.session_state[f"{data_type}_end_month"] = end_month

    # -----------------------------
    # ✅ Dashboard 선택
    # -----------------------------
    dashboards = dashboard_registry.get(data_type, [])

    
    # dashboard 기본값 처리
    if not dashboard_keyword:
        dashboard_keyword = "계약유형"

    
    # ✅ 매칭 개선
    for d in dashboards:
        if dashboard_keyword in d["label"] or dashboard_keyword in d["id"]:
            matched = d["label"]
            break


    if matched:
        st.session_state[f"{data_type}_dashboard_selector"] = matched

    if not intent_data.get("dashboard_supported", True):
        st.warning(intent_data.get("message", "Dashboard 미구축"))
        return
    
    if data_type == "누적" and dashboard_keyword == "누적계정현황":
        dashboard_keyword = "누적 계정 현황"