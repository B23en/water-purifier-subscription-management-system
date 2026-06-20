from pathlib import Path
from datetime import date
import importlib
import streamlit as st
import pandas as pd

from chatbot.chatbot_ui import render_chatbot

from AccountUpdate import run_account_update
from model_mapper import update_model_category
from DB_Updater import run_db_update
from SummaryDB_Builder import run_summary_db_build, get_available_years
from CumulativeDB_Builder import run_cumulative_db_build_single_file


# =========================================================
# 기본 경로
# =========================================================
BASE_DIR = Path(r"V:\한국 정수기 계정")
RAW_DIR = BASE_DIR / "1.RawData"
MODEL_FILE = BASE_DIR / "0.Category" / "ModelCategory.csv"
SUMMARY_DIR = BASE_DIR / "SummaryDB"


# =========================================================
# 유틸
# =========================================================
def get_raw_files():
    if not RAW_DIR.exists():
        return []

    files = []
    for ext in ["*.csv", "*.txt"]:
        files.extend(RAW_DIR.glob(ext))

    return sorted(files, key=lambda x: x.name)


def init_session():
    defaults = {
        "pending_file": None,
        "pending_type": "AUTO",
        "unknown_models": [],
        "last_result": None,
        "selected_data_type": "누적",
        "chat_history": [],
        "api_success": None,
        "api_result": None,
        "force_tab_sync": False,
    }

    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def get_default_period():
    """
    기본 조회기간:
    조회 시점 기준 전년도 1월 ~ 전월
    예) 2026-06-13 조회 시 -> 2025.01 ~ 2026.05
    """
    today = date.today()

    if today.month == 1:
        prev_month_year = today.year - 1
        prev_month = 12
    else:
        prev_month_year = today.year
        prev_month = today.month - 1

    start_month = f"{today.year - 1}.01"
    end_month = f"{prev_month_year}.{prev_month:02d}"

    return start_month, end_month


def validate_ym_format(ym: str):
    try:
        pd.Period(ym.replace(".", "-"), freq="M")
        return True
    except Exception:
        return False


def make_placeholder_renderer(title):
    def _renderer(context):
        st.info(f"'{title}' Dashboard는 아직 구현 전입니다.")
        st.write("전달된 조회 조건")
        st.json({
            "data_type": context.get("data_type"),
            "start_month": context.get("start_month"),
            "end_month": context.get("end_month"),
            "summary_dir": str(context.get("summary_dir")),
        })
    return _renderer


def dynamic_import_renderer(module_path: str, func_name: str, fallback_title: str):
    """
    DashFormat 하위 모듈을 동적으로 import.
    아직 파일이 없으면 placeholder renderer 반환.
    """
    try:
        module = importlib.import_module(module_path)
        return getattr(module, func_name)
    except Exception:
        return make_placeholder_renderer(fallback_title)


# =========================================================
# Dashboard Registry
# =========================================================
DASHBOARD_REGISTRY = {
    
    "누적": [
        {
            "id": "cumulative_account",
            "label": "① 누적 계정 현황",   # ✅ 변경
            "renderer": dynamic_import_renderer(
                module_path="DashFormat.cumulative_account_dashboard",
                func_name="render_dashboard",
                fallback_title="누적 계정 Dashboard"
            ),
        },

        # ✅ ✅ 신규 Dashboard 추가 (여기)
        {
            "id": "cumulative_contract_type",
            "label": "② 계약유형별 누적 계정 현황",
            "renderer": dynamic_import_renderer(
                module_path="DashFormat.cumulative_contract_type_dashboard",
                func_name="render_dashboard",
                fallback_title="계약유형별 누적 계정 Dashboard"
            ),
        },
    ],

    "신규": [
        {
            "id": "new_channel_sales",
            "label": "① 채널별 판매수량",
            "renderer": dynamic_import_renderer(
                module_path="DashFormat.new_channel_sales_dashboard",
                func_name="render_dashboard",
                fallback_title="신규 - 채널별 판매수량"
            ),
        },
        {
            "id": "new_visit_cycle_sales",
            "label": "② 방문주기별 판매수량",
            "renderer": dynamic_import_renderer(
                module_path="DashFormat.new_visit_cycle_sales_dashboard",
                func_name="render_dashboard",
                fallback_title="신규 - 방문주기별 판매수량"
            ),
        },
        {
            "id": "new_contract_type_sales",
            "label": "③ 계약유형별 판매수량",
            "renderer": dynamic_import_renderer(
                module_path="DashFormat.new_contract_type_sales_dashboard",
                func_name="render_dashboard",
                fallback_title="신규 - 계약유형별 판매수량"
            ),
        },
    ],
    "해지": [
        {
            "id": "termination_contract_type_sales",
            "label": "② 계약유형별 해지수량",
            "renderer": dynamic_import_renderer(
                module_path="DashFormat.termination_contract_type_sales_dashboard",
                func_name="render_dashboard",
                fallback_title="해지 - 계약유형별 해지수량"
            ),
        },
    ],
    "만기": [
        {
            "id": "expiration_contract_type_sales",
            "label": "② 계약유형별 만기수량",
            "renderer": dynamic_import_renderer(
                module_path="DashFormat.expiration_contract_type_sales_dashboard",
                func_name="render_dashboard",
                fallback_title="만기 - 계약유형별 만기수량"
            ),
        },
    ],
}


# =========================================================
# 앱 시작
# =========================================================
st.set_page_config(page_title="KR 정수기 계정 운영 시스템", layout="wide")
init_session()

# ✅ 타이틀 영역 (이미지 + 텍스트)
col1, col2 = st.columns([1, 8])

# ✅ 로고 경로
logo_path = Path(r"V:\한국 정수기 계정\PythonCode\IX2.0.jpg")

with col1:
    if logo_path.exists():
        st.image(str(logo_path), width=60)
    else:
        st.warning("로고 파일 없음")

 
with col2:
    st.markdown(
        "<h1 style='margin-bottom:0;'>KR 정수기 계정 현황 조회</h1>",
        unsafe_allow_html=True
    )
st.caption("원본 데이터 가공 / 누적 DB 업데이트 / 요약 DB 생성 / Dashboard 조회")

main_tab1, main_tab2 = st.tabs([
    "📊 데이터 조회",
    "📥 데이터 적재",
])

# =========================================================
# 챗봇 렌더링
# =========================================================
render_chatbot(DASHBOARD_REGISTRY)

# =========================================================
# ✅ 사이드바 - 챗봇 실행 이력
# =========================================================
with st.sidebar:
    st.markdown("### 🤖 챗봇 이력")
    st.caption("최근 5개 기준")

    history = st.session_state.get("chat_history", [])

    if not history:
        st.caption("아직 실행 이력이 없습니다.")
    else:
        for i, item in enumerate(history, 1):
            status_icon = "✅" if item["status"] == "성공" else "❌"

            st.markdown(
                f"""
                **{i}. {item['question']}**  
                {status_icon} {item['status']}
                """,
                unsafe_allow_html=True
            )
            st.markdown("---")



    st.markdown("### ☁️ Azure API 상태")
    if st.session_state.get("api_success") is True:
        st.success("Azure API 호출 성공")
    elif st.session_state.get("api_success") is False:
        st.error("Azure API 호출 실패")
    else:
        st.caption("아직 호출 이력이 없습니다.")

    if st.session_state.get("api_result"):
        with st.expander("API 응답 결과 보기", expanded=False):
            st.code(st.session_state["api_result"], language="json")


# =========================================================
# 📥 데이터 적재
# =========================================================
with main_tab2:
    sub_tab1, sub_tab2, sub_tab3, sub_tab4 = st.tabs([
        "① 원본 데이터 가공",
        "② 누적 DB 업데이트",
        "③ 요약 DB 생성",
        "④ 누적계정 DB 생성",
    ])

    # =========================================================
    # ① 원본 데이터 가공
    # =========================================================
    with sub_tab1:
        st.subheader("원본 데이터 가공")

        raw_files = get_raw_files()
        raw_names = [f.name for f in raw_files]

        col1, col2 = st.columns([2, 1])

        with col1:
            selected_file = st.selectbox(
                "가공할 원본 파일 선택",
                options=raw_names if raw_names else [""],
                key="raw_selected_file"
            )

        with col2:
            forced_type = st.selectbox(
                "데이터구분(선택)",
                ["AUTO", "신규", "해지", "만기", "누적"],
                index=0,
                key="raw_forced_type"
            )

        if st.button("가공 실행", type="primary", use_container_width=True, key="raw_run_button"):
            if not selected_file:
                st.warning("원본 파일이 없습니다.")
            else:
                file_path = RAW_DIR / selected_file
                result = run_account_update(file_path, forced_type=forced_type)

                st.session_state["last_result"] = result

                if result["status"] == "NEED_MODEL_INPUT":
                    st.session_state["pending_file"] = selected_file
                    st.session_state["pending_type"] = forced_type
                    st.session_state["unknown_models"] = result["unknown_models"]
                    st.warning("ModelCategory에 없는 신규 모델이 있습니다. 아래에서 입력 후 재실행해 주세요.")

                elif result["status"] == "DONE":
                    st.session_state["pending_file"] = None
                    st.session_state["pending_type"] = "AUTO"
                    st.session_state["unknown_models"] = []
                    st.success(
                        f"가공 완료\n"
                        f"- 데이터구분: {result['data_type']}\n"
                        f"- 저장파일: {result['output_file']}\n"
                        f"- 건수: {result['row_count']:,}"
                    )
                else:
                    st.error(result.get("message", "가공 중 오류가 발생했습니다."))

        # 신규 모델 입력 영역
        if st.session_state["unknown_models"]:
            st.markdown("---")
            st.markdown("### 신규 모델 정보 입력")

            with st.form("new_model_form"):
                new_rows = []

                for model in st.session_state["unknown_models"]:
                    st.markdown(f"#### 모델: `{model}`")
                    c1, c2, c3 = st.columns(3)

                    with c1:
                        tool = st.text_input(
                            f"{model}_tool",
                            label_visibility="collapsed",
                            placeholder="Tool 입력"
                        )
                    with c2:
                        model_name = st.text_input(
                            f"{model}_name",
                            value=model,
                            label_visibility="collapsed",
                            placeholder="모델명 입력"
                        )
                    with c3:
                        func = st.text_input(
                            f"{model}_func",
                            label_visibility="collapsed",
                            placeholder="기능 입력"
                        )

                    new_rows.append({
                        "모델": model,
                        "Tool": tool,
                        "모델명": model_name,
                        "기능": func,
                    })

                submitted = st.form_submit_button(
                    "ModelCategory 저장 후 재실행",
                    use_container_width=True
                )

                if submitted:
                    invalid_rows = [
                        r for r in new_rows
                        if not r["Tool"] or not r["모델명"] or not r["기능"]
                    ]

                    if invalid_rows:
                        st.error("신규 모델의 Tool / 모델명 / 기능은 모두 입력해 주세요.")
                    else:
                        update_model_category(MODEL_FILE, new_rows)

                        file_path = RAW_DIR / st.session_state["pending_file"]
                        result = run_account_update(
                            file_path,
                            forced_type=st.session_state["pending_type"]
                        )

                        st.session_state["last_result"] = result

                        if result["status"] == "DONE":
                            st.session_state["pending_file"] = None
                            st.session_state["pending_type"] = "AUTO"
                            st.session_state["unknown_models"] = []
                            st.success(
                                f"재실행 완료\n"
                                f"- 데이터구분: {result['data_type']}\n"
                                f"- 저장파일: {result['output_file']}\n"
                                f"- 건수: {result['row_count']:,}"
                            )
                        else:
                            st.error(result.get("message", "재실행 중 오류가 발생했습니다."))

        if st.session_state["last_result"]:
            with st.expander("최근 실행 결과 보기", expanded=False):
                st.write(st.session_state["last_result"])

    # =========================================================
    # ② 누적 DB 업데이트
    # =========================================================
    with sub_tab2:
        st.subheader("누적 DB 업데이트")

        selected_types = st.multiselect(
            "적재할 데이터구분 선택",
            ["신규", "해지", "만기"],
            default=["신규", "해지", "만기"],
            key="db_update_types"
        )

        if st.button("DB 업데이트 실행", type="primary", use_container_width=True, key="db_update_run"):
            logs = run_db_update(selected_types=selected_types)
            st.success("DB 업데이트 작업이 완료되었습니다.")
            st.text("\n".join(logs))

    # =========================================================
    # ③ 요약 DB 생성
    # =========================================================
    with sub_tab3:
        st.subheader("월 단위 요약 DB 생성")
        st.caption("3.KR_DB 하위 연도별 원천 데이터를 읽어 SummaryDB를 생성합니다.")

        summary_types = st.multiselect(
            "요약 대상 선택",
            ["신규", "해지", "만기"],
            default=["신규", "해지", "만기"],
            key="summary_build_types"
        )

        available_years = get_available_years(summary_types)

        selected_years = st.multiselect(
            "처리할 연도 선택",
            options=available_years,
            default=available_years,
            key="summary_build_years"
        )

        if st.button("요약 DB 생성 실행", type="primary", use_container_width=True, key="summary_build_run"):
            if not summary_types:
                st.warning("요약할 데이터구분을 선택해 주세요.")
            elif not selected_years:
                st.warning("대상 연도를 선택해 주세요.")
            else:
                st.info("연도별 원천 파일을 순차적으로 읽어 월 단위 요약 DB를 생성합니다.")

                progress_bar = st.progress(0)
                status_placeholder = st.empty()
                log_placeholder = st.empty()

                live_logs = []

                def progress_callback(current, total, message):
                    percent = int(current / total * 100) if total else 0
                    progress_bar.progress(percent)
                    status_placeholder.info(f"{percent}% | {message}")

                def log_callback(message):
                    live_logs.append(message)
                    log_placeholder.text("\n".join(live_logs[-30:]))

                results = run_summary_db_build(
                    selected_types=summary_types,
                    selected_years=selected_years,
                    progress_callback=progress_callback,
                    log_callback=log_callback
                )

                progress_bar.progress(100)
                status_placeholder.success("요약 DB 생성이 완료되었습니다.")

                result_rows = []
                for r in results:
                    result_rows.append({
                        "데이터구분": r["data_type"],
                        "상태": r["status"],
                        "처리파일수": r["file_count"],
                        "결과행수": r["row_count"],
                        "저장파일": r["output_file"] if r["output_file"] else "",
                    })

                st.markdown("### 결과 요약")
                st.dataframe(pd.DataFrame(result_rows), use_container_width=True)

                with st.expander("전체 로그 보기", expanded=False):
                    all_logs = []
                    for r in results:
                        all_logs.extend(r.get("logs", []))
                    st.text("\n".join(all_logs))

    # =========================================================
    # ④ 누적계정 DB 생성
    # =========================================================
    with sub_tab4:
        st.subheader("누적계정 DB 생성 (단일 parquet)")
        st.caption("2019.12 기초 누적계정 파일을 포함해 2020.01부터 월별 누적계정 데이터를 계산하여 하나의 parquet 파일(누적_년월.parquet)로 저장합니다.")

        cumulative_base_file = st.text_input(
            "기초 누적계정 파일명",
            value="누적_2019.12.parquet",
            key="cumulative_base_file"
        )

        cumulative_output_file = st.text_input(
            "출력 파일명",
            value="누적_년월.parquet",
            key="cumulative_output_file"
        )

        cumulative_start_month = st.text_input(
            "계산 시작월",
            value="2020.01",
            key="cumulative_start_month"
        )

        if st.button("누적계정 DB 생성 실행", type="primary", use_container_width=True, key="cumulative_build_run"):

            if not validate_ym_format(cumulative_start_month):
                st.error("계산 시작월 형식이 올바르지 않습니다. 예: 2020.01")
            else:
                st.info("2019.12 기초 누적 + 신규/해지/만기 요약 DB를 이용해 단일 parquet 파일을 생성합니다.")

                progress_bar = st.progress(0)
                status_placeholder = st.empty()
                log_placeholder = st.empty()

                live_logs = []

                def progress_callback(current, total, message):
                    percent = int(current / total * 100) if total else 0
                    progress_bar.progress(percent)
                    status_placeholder.info(f"{percent}% | {message}")

                def log_callback(message):
                    live_logs.append(message)
                    log_placeholder.text("\n".join(live_logs[-30:]))

                try:
                    result = run_cumulative_db_build_single_file(
                        base_file_name=cumulative_base_file,
                        output_file_name=cumulative_output_file,
                        start_month=cumulative_start_month,
                        progress_callback=progress_callback,
                        log_callback=log_callback,
                    )

                    progress_bar.progress(100)
                    status_placeholder.success("누적 DB 생성이 완료되었습니다.")

                    st.markdown("### 결과 요약")
                    st.dataframe(pd.DataFrame([{
                        "상태": result["status"],
                        "저장파일": result["output_file"],
                        "총 행수": result["row_count"],
                        "포함 기준월 수": result["month_count"],
                    }]), use_container_width=True)

                    with st.expander("전체 로그 보기", expanded=False):
                        st.text("\n".join(live_logs))

                except Exception as e:
                    st.error(f"누적 DB 생성 중 오류가 발생했습니다: {e}")


# =========================================================
# 📊 데이터 조회
# =========================================================
with main_tab1:

    

    tab_options = ["누적", "신규", "해지", "만기"]

    # ✅ ✅ 1회성 sync
    if st.session_state.get("force_tab_sync", False):
        st.session_state["main_type_selector"] = st.session_state["selected_data_type"]
        st.session_state["force_tab_sync"] = False   # ✅ 중요 (1회만 실행)

    selected_tab = st.radio(
        "데이터 구분",
        tab_options,
        horizontal=True,
        key="main_type_selector"
    )

    # ✅ radio → session 반영
    st.session_state["selected_data_type"] = selected_tab



    def render_dashboard_group(data_type: str):
        st.subheader(f"{data_type} Dashboard")

        dashboards = DASHBOARD_REGISTRY.get(data_type, [])
        if not dashboards:
            st.warning(f"{data_type} Dashboard가 등록되어 있지 않습니다.")
            return

        # ---------------------------------------------
        # 공통 조회기간 (연월 단위)
        # ---------------------------------------------
        default_start_month, default_end_month = get_default_period()

        start_key = f"{data_type}_start_month"
        end_key = f"{data_type}_end_month"

        # ✅ 값이 없거나 비어있으면 default 적용
        if start_key not in st.session_state or not st.session_state[start_key]:
            st.session_state[start_key] = default_start_month

        if end_key not in st.session_state or not st.session_state[end_key]:
            st.session_state[end_key] = default_end_month

        c1, c2 = st.columns([1, 1])
        with c1:
            start_month = st.text_input(
                "조회 시작 연월",
                key=start_key
            )
        with c2:
            end_month = st.text_input(
                "조회 종료 연월",
                key=end_key
            )

        if not validate_ym_format(start_month):
            st.error("조회 시작 연월 형식이 올바르지 않습니다. 예: 2025.01")
            return

        if not validate_ym_format(end_month):
            st.error("조회 종료 연월 형식이 올바르지 않습니다. 예: 2026.05")
            return

        start_period = pd.Period(start_month.replace(".", "-"), freq="M")
        end_period = pd.Period(end_month.replace(".", "-"), freq="M")

        if start_period > end_period:
            st.error("조회 시작 연월이 조회 종료 연월보다 늦을 수 없습니다.")
            return

        st.caption(f"조회기간: {start_month} ~ {end_month}")

        # ---------------------------------------------
        # Dashboard 선택
        # ---------------------------------------------
        dashboard_labels = [d["label"] for d in dashboards]
        selected_label = st.radio(
            "Dashboard 선택",
            options=dashboard_labels,
            horizontal=True,
            key=f"{data_type}_dashboard_selector"
        )

        selected_dashboard = next(d for d in dashboards if d["label"] == selected_label)

        context = {
            "data_type": data_type,
            "start_month": start_month,
            "end_month": end_month,
            "summary_dir": SUMMARY_DIR,
        }

        st.markdown("---")
        selected_dashboard["renderer"](context)

    if selected_tab == "신규":
        render_dashboard_group("신규")
    elif selected_tab == "해지":
        render_dashboard_group("해지")
    elif selected_tab == "만기":
        render_dashboard_group("만기")
    elif selected_tab == "누적":
        render_dashboard_group("누적")