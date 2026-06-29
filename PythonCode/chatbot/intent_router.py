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

    # -----------------------------
    # ✅ 데이터 범위 초과 보정 (예: "이번달"=미래월인데 데이터는 전월까지)
    #    YYYY.MM 은 0패딩 동일포맷이라 문자열 비교로 대소 판정 가능.
    #    예측은 기간을 쓰지 않으므로(다음달 예측이 본질) 보정·안내 대상에서 제외.
    # -----------------------------
    is_forecast = bool(dashboard_keyword) and "예측" in dashboard_keyword
    if not is_forecast:
        period_notice = ""
        if end_month and end_month > today:
            period_notice = (
                f"요청하신 {end_month}는 아직 데이터가 없어 "
                f"최신 데이터 월({today}) 기준으로 표시합니다."
            )
            end_month = today
        if start_month and start_month > today:
            start_month = today
        if start_month and end_month and start_month > end_month:
            start_month = end_month
        if period_notice:
            st.info(period_notice)

    # ✅ 적용 (data_type 이 비어 있으면 쓰레기 키 생성 방지)
    if data_type and start_month:
        st.session_state[f"{data_type}_start_month"] = start_month

    if data_type and end_month:
        st.session_state[f"{data_type}_end_month"] = end_month

    # ✅ 요인분석 + 단일월이면 세그먼트 대시보드를 '특정 월(MoM/YoY)' 모드로 열고 월 주입
    #    (예: "저저번달 신규 왜 줄었어" → 신규/요인분석 + 2026.04 월분석 화면이 바로 뜸)
    if (
        data_type in ("신규", "해지", "만기")
        and dashboard_keyword
        and "요인분석" in dashboard_keyword
        and start_month
        and start_month == end_month
    ):
        st.session_state[f"seg_mode_{data_type}"] = "특정 월 (MoM/YoY)"
        st.session_state[f"seg_month_{data_type}"] = start_month

    # -----------------------------
    # ✅ Dashboard 선택
    # -----------------------------
    # 미구축 대시보드면 선택하지 않고 안내 후 종료
    if not intent_data.get("dashboard_supported", True):
        st.warning(intent_data.get("message", "Dashboard 미구축"))
        return

    dashboards = dashboard_registry.get(data_type, [])

    # dashboard 기본값 처리
    if not dashboard_keyword:
        dashboard_keyword = "계약유형"

    # ✅ 공백 무시 substring 매칭
    #    (라벨 "① 누적 계정 현황" vs 키워드 "누적계정현황" 불일치 해소)
    #    matched 는 미매칭 시 NameError 방지를 위해 None 으로 초기화한다.
    matched = None
    key = dashboard_keyword.replace(" ", "")
    for d in dashboards:
        if key in d["label"].replace(" ", "") or key in d["id"]:
            matched = d["label"]
            break

    if matched:
        st.session_state[f"{data_type}_dashboard_selector"] = matched
