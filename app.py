"""쇼핑 리스트 앱 (Streamlit) - PRD.md 참고.

화면과 사용자 동작(콜백)만 다룬다. 데이터 저장은 storage.py가 맡는다.

- 상태 변경은 모두 위젯의 on_click / on_change 콜백에서 storage 함수를 불러 처리한다.
  콜백은 스크립트 재실행 전에 실행되므로 변경 내용이 같은 실행에서 바로 반영된다.
- 아이템은 매 실행마다 storage.load_items()로 파일에서 다시 읽어
  session_state["items"]에 넣는다 (새로고침/다른 탭 변경 반영).
"""

import re
import time
import uuid

import streamlit as st

import storage
from storage import MAX_QUANTITY

DOUBLE_SUBMIT_WINDOW = 1.5  # 초. 추가 직후 이 시간 안의 빈 제출은 더블클릭으로 보고 무시


@st.cache_resource
def _recent_adds() -> dict[str, float]:
    """세션별 마지막 추가 성공 시각 {세션 key: time.monotonic()}.

    더블클릭하면 두 제출의 콜백이 거의 동시에 실행되는데, 이때 먼저 실행된(중단된)
    실행에서 session_state에 쓴 값은 다음 콜백에 보이지 않는다(브라우저 테스트로 확인).
    그래서 session_state가 아니라 서버 메모리에 기록한다.
    """
    return {}


def report(notice: storage.Notice) -> None:
    """storage가 돌려준 안내 문구(저장 파일 문제)를 다음 화면에 표시하도록 남긴다."""
    if notice:
        st.session_state["load_warning"] = notice


# ---------------------------------------------------------------------------
# 상태 관리
# ---------------------------------------------------------------------------
def init_state() -> None:
    """session_state 초기화. 아이템은 매 실행마다 파일에서 새로 읽는다.

    주의: st.session_state.items는 dict의 items() 메서드와 충돌하므로
    반드시 st.session_state["items"]로 접근한다.
    """
    defaults = {
        "editing_id": None,    # 편집 중인 아이템 id (한 번에 하나)
        "edit_orig": None,     # 편집 시작 시점의 이름/수량 (바뀐 필드만 저장하기 위해)
        "add_warning": None,   # 추가 폼 경고 메시지 (한 번 표시 후 지움)
        "edit_warning": None,  # 수정 폼 경고 메시지 (한 번 표시 후 지움)
        "load_warning": None,  # 저장 파일 오류 메시지 (한 번 표시 후 지움)
        "session_key": str(uuid.uuid4()),  # _recent_adds()에서 이 세션을 찾는 key
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    items, notice = storage.load_items()
    st.session_state["items"] = items
    report(notice)

    # 더블클릭 기록은 서버 메모리에 남으므로 오래된 세션 기록은 정리한다.
    recent = _recent_adds()
    now = time.monotonic()
    for key in [k for k, t in recent.items() if now - t > 3600]:
        recent.pop(key, None)


# ---------------------------------------------------------------------------
# 콜백 (위젯 이벤트 → 상태 변경)
# ---------------------------------------------------------------------------
def on_add_submit() -> None:
    recent = _recent_adds()
    session_key = st.session_state["session_key"]
    name = st.session_state["new_name"].strip()
    quantity = int(st.session_state["new_qty"])
    if not name:
        # 추가 직후의 빈 제출은 더블클릭/두 번 탭으로 보고 조용히 무시한다.
        # (첫 클릭에서 입력창이 비워진 뒤 두 번째 클릭이 빈 폼을 제출하기 때문)
        if time.monotonic() - recent.get(session_key, 0.0) > DOUBLE_SUBMIT_WINDOW:
            st.session_state["add_warning"] = "아이템 이름을 입력해 주세요."
        return
    # 더블클릭하면 두 번째 제출이 첫 번째 실행을 중단시킨다. Streamlit은 session_state를
    # 읽고 쓸 때마다 중단 요청을 확인하므로(StopException), 시각 기록을 파일 저장보다 먼저 한다.
    recent[session_key] = time.monotonic()
    report(storage.add_item(name, quantity))
    st.session_state["add_warning"] = None


def on_check_change(item_id: str) -> None:
    report(storage.set_checked(item_id, st.session_state[f"chk_{item_id}"]))


def on_edit_start(item_id: str) -> None:
    item = storage.get_item(item_id)
    if item is None:  # 다른 탭에서 이미 삭제됨
        return
    st.session_state["editing_id"] = item_id
    st.session_state["edit_orig"] = {"name": item["name"], "quantity": item["quantity"]}
    # 편집 입력창을 항상 파일의 최신 값으로 시작한다.
    st.session_state[f"edit_name_{item_id}"] = item["name"]
    st.session_state[f"edit_qty_{item_id}"] = item["quantity"]
    st.session_state["edit_warning"] = None


def on_edit_save(item_id: str) -> None:
    name = st.session_state[f"edit_name_{item_id}"].strip()
    if not name:
        st.session_state["edit_warning"] = "이름은 비워둘 수 없습니다."
        return
    quantity = int(st.session_state[f"edit_qty_{item_id}"])

    # 사용자가 실제로 바꾼 필드만 저장한다.
    # 편집하는 동안 다른 탭에서 바꾼 필드를 옛 값으로 덮어쓰지 않기 위해서다.
    orig = st.session_state["edit_orig"] or {}
    report(storage.update_item(
        item_id,
        name=name if name != orig.get("name") else None,
        quantity=quantity if quantity != orig.get("quantity") else None,
    ))
    st.session_state["editing_id"] = None
    st.session_state["edit_warning"] = None


def on_edit_cancel() -> None:
    st.session_state["editing_id"] = None
    st.session_state["edit_warning"] = None


def on_delete(item_id: str) -> None:
    report(storage.delete_item(item_id))
    if st.session_state["editing_id"] == item_id:
        st.session_state["editing_id"] = None


def on_delete_checked() -> None:
    # 편집 중이던 아이템이 지워졌으면 render_item_list()가 편집 상태를 푼다.
    report(storage.delete_checked_items())


def on_delete_all() -> None:
    report(storage.delete_all_items())
    st.session_state["editing_id"] = None


# ---------------------------------------------------------------------------
# 화면 렌더링
# ---------------------------------------------------------------------------
# 색은 고정값 대신 opacity와 inherit만 써서 라이트/다크 테마를 그대로 따른다.
# 행 스타일은 st.container(key=...)가 붙여 주는 클래스 .st-key-<key>로 지정한다.
#   .st-key-add-row        : 입력 행
#   .st-key-row-todo-<id>  : 미완료 아이템 행
#   .st-key-row-done-<id>  : 완료 아이템 행 (취소선)
#   .st-key-edit-<id>      : 수정 중인 행
CUSTOM_CSS = """
<style>
/* 입력 행, 아이템 행, 수정 행은 좁은 화면에서도 세로로 쌓이지 않고 한 줄 유지 */
.st-key-add-row [data-testid="stHorizontalBlock"],
[class*="st-key-row-"] [data-testid="stHorizontalBlock"],
[class*="st-key-edit-"] [data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
    gap: 0.5rem;
}
.st-key-add-row [data-testid="stColumn"],
[class*="st-key-row-"] [data-testid="stColumn"],
[class*="st-key-edit-"] [data-testid="stColumn"] {
    min-width: 0 !important;
}

/* 아이템 목록: 행 간격을 촘촘하게, 행 사이 얇은 구분선
   각 행은 stLayoutWrapper 안에 혼자 들어 있어서 행 자체에 :last-child를 쓰면
   모든 행이 걸린다. 그래서 감싸는 wrapper 기준으로 마지막 행을 뺀다.
   선은 Streamlit 컨테이너 스타일이 border를 덮어써서 box-shadow로 그린다. */
.st-key-item-list [data-testid="stVerticalBlock"] { gap: 0; }
[class*="st-key-row-"] { padding: 0.35rem 0; }
.st-key-item-list > [data-testid="stLayoutWrapper"]:not(:last-child) > [class*="st-key-row-"] {
    box-shadow: inset 0 -1px 0 rgba(128, 128, 128, 0.2);
}

/* 긴 이름은 줄바꿈 (띄어쓰기 없는 긴 문자열 포함) */
[class*="st-key-row-"] [data-testid="stCheckbox"] p {
    overflow-wrap: anywhere;
    font-size: 1.05rem;
}

/* 구매 완료 아이템: 취소선 + 흐리게 */
[class*="st-key-row-done-"] [data-testid="stCheckbox"] p,
[class*="st-key-row-done-"] [data-testid="stCaptionContainer"] {
    text-decoration: line-through;
    opacity: 0.5;
}

/* 아이콘 버튼: 작고 정사각형, 손가락으로 누르기 쉬운 최소 크기 유지 */
[class*="st-key-row-"] [data-testid="stButton"] button {
    min-height: 2.25rem;
    min-width: 2.25rem;
    padding: 0 0.4rem;
}
[class*="st-key-row-"] [data-testid="stColumn"]:not(:first-child) {
    flex: 0 0 auto !important;
    width: auto !important;
}

/* 수량 표시 */
[class*="st-key-row-"] [data-testid="stCaptionContainer"] {
    white-space: nowrap;
    font-size: 0.95rem;
}

/* 추가 버튼: 글자 줄바꿈 없이 내용 너비만큼 */
.st-key-add-row [data-testid="stColumn"]:last-child {
    flex: 0 0 auto !important;
    width: auto !important;
}
.st-key-add-row button p { white-space: nowrap; }

/* 모바일 (좁은 화면) */
@media (max-width: 640px) {
    [data-testid="stMainBlockContainer"] { padding-top: 2.5rem; }
    h1 { font-size: 1.9rem !important; white-space: nowrap; }
    [class*="st-key-row-"] [data-testid="stHorizontalBlock"] { gap: 0.15rem; }
    .st-key-add-row [data-testid="stHorizontalBlock"] { gap: 0.35rem; }
}
</style>
"""

_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|~<>:$&])")

# 마크다운 자동 링크(www.~, http://~, a@b.com)는 파싱이 끝난 글자에 적용되므로
# 이스케이프나 HTML 문자 참조로는 막히지 않는다(브라우저 테스트로 확인).
# 링크 패턴이 성립하는 지점에 보이지 않는 문자(U+2060 WORD JOINER)를 넣어 끊는다.
_WJ = chr(0x2060)
# 패턴은 이스케이프된 글자(www\. / http\:)에 적용되므로 백슬래시를 선택적으로 허용한다.
_AUTOLINK_BREAKS = [
    (re.compile(r"(?i)\b(www)(?=\\?\.)"), r"\1" + _WJ),                    # www.naver.com
    (re.compile(r"(?i)\b(https?|ftp|mailto|xmpp)(?=\\?:)"), r"\1" + _WJ),  # http://~
    (re.compile(r"@"), "@" + _WJ),                                          # a@b.com
]


def escape_md(text: str) -> str:
    """체크박스 라벨은 마크다운으로 해석되므로 사용자 입력을 글자 그대로 보이게 한다.

    예: '**우유**'가 굵게, ':red[우유]'가 빨간색, '$x$'가 수식,
    'www.naver.com'이 링크로 바뀌는 것을 막는다.
    """
    escaped = _MD_SPECIAL.sub(r"\\\1", text)
    for pattern, repl in _AUTOLINK_BREAKS:
        escaped = pattern.sub(repl, escaped)
    return escaped


def show_once(key: str, kind: str = "warning") -> None:
    """경고/오류 메시지를 한 번만 표시하고 지운다. 다음 동작 때 남아 있지 않게 한다."""
    message = st.session_state[key]
    if message:
        getattr(st, kind)(message, icon="⚠️")
        st.session_state[key] = None


def render_header() -> None:
    st.title("🛒 쇼핑 리스트")
    show_once("load_warning", "error")

    items = st.session_state["items"]
    total = len(items)
    done = sum(1 for i in items if i["checked"])
    ratio = done / total if total else 0.0

    st.progress(ratio, text=f"**{done} / {total}** 구매 완료 · {round(ratio * 100)}%")
    if total and done == total:
        st.success("🎉 모든 쇼핑을 완료했어요!")


def render_input_form() -> None:
    with st.form("add_item_form", clear_on_submit=True, border=True):
        with st.container(key="add-row"):
            col_name, col_qty, col_btn = st.columns(
                [5, 2, 1.4], vertical_alignment="bottom"
            )
            col_name.text_input(
                "아이템 이름", placeholder="예: 우유", key="new_name"
            )
            col_qty.number_input(
                "수량", min_value=1, max_value=MAX_QUANTITY, value=1, step=1,
                key="new_qty",
            )
            col_btn.form_submit_button(
                "추가", type="primary", on_click=on_add_submit, width="stretch"
            )

    show_once("add_warning")


def render_item_row(item: dict) -> None:
    item_id = item["id"]
    state = "done" if item["checked"] else "todo"

    # 체크박스 위젯은 key가 있으면 처음 값을 계속 기억한다(value= 인자 무시).
    # 다른 탭에서 바뀐 체크 상태가 화면에 반영되도록 매번 파일 값으로 맞춘다.
    st.session_state[f"chk_{item_id}"] = item["checked"]

    with st.container(key=f"row-{state}-{item_id}"):
        col_chk, col_qty, col_edit, col_del = st.columns(
            [6, 1, 1, 1], vertical_alignment="center"
        )
        col_chk.checkbox(
            escape_md(item["name"]),
            key=f"chk_{item_id}",
            on_change=on_check_change,
            args=(item_id,),
        )
        col_qty.caption(f"x{item['quantity']}")
        col_edit.button(
            "✏️", key=f"edit_{item_id}", help="수정", type="tertiary",
            on_click=on_edit_start, args=(item_id,),
        )
        col_del.button(
            "🗑️", key=f"del_{item_id}", help="삭제", type="tertiary",
            on_click=on_delete, args=(item_id,),
        )


def render_edit_row(item: dict) -> None:
    item_id = item["id"]
    with st.container(border=True, key=f"edit-{item_id}"):
        col_name, col_qty = st.columns([3, 1.4])
        # 초기값은 on_edit_start에서 session_state로 넣는다.
        col_name.text_input("이름", key=f"edit_name_{item_id}")
        col_qty.number_input(
            "수량", min_value=1, max_value=MAX_QUANTITY, step=1,
            key=f"edit_qty_{item_id}",
        )

        col_save, col_cancel = st.columns(2)
        col_save.button(
            "저장", key=f"save_{item_id}", type="primary", width="stretch",
            on_click=on_edit_save, args=(item_id,),
        )
        col_cancel.button(
            "취소", key=f"cancel_{item_id}", width="stretch",
            on_click=on_edit_cancel,
        )
        show_once("edit_warning")


def render_item_list() -> None:
    items = st.session_state["items"]

    # 편집 중인 아이템이 다른 탭에서 삭제됐으면 편집 상태를 푼다.
    if st.session_state["editing_id"] not in {i["id"] for i in items}:
        st.session_state["editing_id"] = None

    if not items:
        st.info("아직 추가된 아이템이 없습니다. 위에서 살 물건을 추가해 보세요.", icon="📝")
        return

    with st.container(border=True, key="item-list"):
        for item in items:
            if item["id"] == st.session_state["editing_id"]:
                render_edit_row(item)
            else:
                render_item_row(item)


def render_bulk_actions() -> None:
    items = st.session_state["items"]
    if not items:
        return
    has_checked = any(i["checked"] for i in items)

    col_checked, col_all = st.columns(2)
    col_checked.button(
        "✅ 체크된 항목 삭제", disabled=not has_checked,
        on_click=on_delete_checked, width="stretch",
    )
    # 전체 삭제는 되돌릴 수 없으므로 한 번 더 확인받는다.
    with col_all.popover("🧹 전체 삭제", width="stretch"):
        st.write(f"아이템 **{len(items)}개**를 모두 삭제할까요?  \n되돌릴 수 없습니다.")
        st.button(
            "모두 삭제", key="confirm_delete_all", type="primary", width="stretch",
            on_click=on_delete_all,
        )


def main() -> None:
    st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒", layout="centered")
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    init_state()
    render_header()
    render_input_form()
    render_item_list()
    render_bulk_actions()


if __name__ == "__main__":
    main()
