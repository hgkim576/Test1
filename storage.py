"""쇼핑 리스트 저장소 (JSON 파일).

Streamlit에 의존하지 않는 순수 Python 모듈이다. app.py는 이 모듈의 함수만 써서 데이터를 다룬다.

- 저장 파일(DATA_FILE)이 유일한 원본이다. 화면은 매 실행마다 load_items()로 다시 읽는다.
- 모든 변경은 _mutate()를 거쳐 "잠금 → 읽기 → 수정 → 저장"을 한 번에 한다.
  여러 탭/사용자가 동시에 저장해도 서로의 변경이 사라지지 않는다.
- 저장은 임시 파일에 쓴 뒤 os.replace로 교체해서, 중간에 멈춰도 파일이 깨지지 않는다.
- 변경 함수는 파일을 읽다가 문제가 생겼을 때의 안내 문구(str)를 돌려준다. 문제가 없으면 None.

저장 파일 위치는 환경변수 SHOPPING_LIST_FILE로 바꿀 수 있다(테스트에서 실제 데이터를 건드리지 않기 위해).
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

DATA_FILE = Path(
    os.environ.get("SHOPPING_LIST_FILE") or Path(__file__).parent / "shopping_list.json"
)
MAX_QUANTITY = 999

# 모든 세션(탭)이 함께 쓰는 잠금.
# app.py는 실행마다 다시 실행되지만 import한 모듈은 서버 프로세스에 한 번만 올라가므로
# 이 잠금은 모든 세션이 공유한다.
_lock = threading.RLock()

Notice = str | None  # 안내 문구 (없으면 None)


# ---------------------------------------------------------------------------
# 파일 읽기/쓰기
# ---------------------------------------------------------------------------
def clamp_quantity(quantity: object) -> int:
    """수량을 1~MAX_QUANTITY 정수로 맞춘다. 숫자가 아니면 1."""
    try:
        value = int(quantity)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 1
    return min(max(value, 1), MAX_QUANTITY)


def _normalize(entry: object, seen_ids: set[str]) -> dict | None:
    """저장된 항목 하나를 PRD 4장 형식으로 맞춘다. 살릴 수 없으면 None."""
    if not isinstance(entry, dict):
        return None
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        return None

    item_id = entry.get("id")
    if not isinstance(item_id, str) or not item_id or item_id in seen_ids:
        item_id = str(uuid.uuid4())
    seen_ids.add(item_id)

    created_at = entry.get("created_at")
    return {
        "id": item_id,
        "name": name.strip(),
        "quantity": clamp_quantity(entry.get("quantity", 1)),
        "checked": entry.get("checked") is True,
        "created_at": created_at if isinstance(created_at, str) else "",
    }


def _backup_file(reason: str) -> str:
    """현재 파일을 broken-<시각>.json으로 옮기고 안내 문구를 돌려준다."""
    backup = DATA_FILE.with_name(
        f"{DATA_FILE.stem}.broken-{datetime.now():%Y%m%d%H%M%S}.json"
    )
    DATA_FILE.replace(backup)
    return f"{reason} 원래 파일은 {backup.name}에 보관했습니다."


def load_items() -> tuple[list[dict], Notice]:
    """파일에서 아이템 목록을 읽는다. (아이템 목록, 안내 문구)를 돌려준다.

    - 파일이 없으면: 빈 리스트
    - JSON이 깨졌거나 리스트가 아니면: 파일을 백업하고 빈 리스트로 시작
    - 일부 항목만 잘못됐으면: 원본을 백업하고 살릴 수 있는 항목만 남겨 저장
    - 형식만 조금 다르면(수량이 문자열 등): 고쳐서 다시 저장 (안내 없음)
    """
    with _lock:
        if not DATA_FILE.exists():
            return [], None
        try:
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return [], _backup_file("저장 파일을 읽을 수 없어 새로 시작합니다.")
        if not isinstance(raw, list):
            return [], _backup_file("저장 파일 형식이 올바르지 않아 새로 시작합니다.")

        seen: set[str] = set()
        items = [n for n in (_normalize(e, seen) for e in raw) if n is not None]
        warning = None
        if len(items) != len(raw):
            dropped = len(raw) - len(items)
            warning = _backup_file(f"저장 파일에서 읽을 수 없는 항목 {dropped}개를 제외했습니다.")
            save_items(items)
        elif items != raw:
            save_items(items)
        return items, warning


def save_items(items: list[dict]) -> None:
    """임시 파일에 쓴 뒤 교체해서, 저장 중 중단돼도 파일이 깨지지 않게 한다."""
    with _lock:
        tmp = DATA_FILE.with_name(f".{DATA_FILE.name}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, DATA_FILE)


def _mutate(change: Callable[[list[dict]], list[dict] | None]) -> Notice:
    """잠금 안에서 읽기 → 수정 → 저장을 한 번에 한다.

    change는 리스트를 직접 고치거나(None 반환) 새 리스트를 반환한다.
    """
    with _lock:
        items, warning = load_items()
        result = change(items)
        save_items(items if result is None else result)
        return warning


# ---------------------------------------------------------------------------
# 아이템 조작 (PRD 3장)
# ---------------------------------------------------------------------------
def get_item(item_id: str) -> dict | None:
    """id로 아이템 하나를 찾는다. 없으면 None (다른 탭에서 삭제된 경우 등)."""
    items, _ = load_items()
    return next((i for i in items if i["id"] == item_id), None)


def add_item(name: str, quantity: int = 1) -> Notice:
    """새 아이템을 리스트 끝에 추가한다. 이름 앞뒤 공백은 지운다.

    빈 이름 검사는 화면(app.py)에서 경고와 함께 처리한다.
    """
    new = {
        "id": str(uuid.uuid4()),
        "name": name.strip(),
        "quantity": clamp_quantity(quantity),
        "checked": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    return _mutate(lambda items: items.append(new))


def update_item(
    item_id: str, *, name: str | None = None, quantity: int | None = None
) -> Notice:
    """아이템 이름/수량 수정. None인 필드는 건드리지 않는다.

    바뀐 필드만 넘기면, 편집하는 동안 다른 탭에서 바꾼 필드를 덮어쓰지 않는다.
    """
    def change(items: list[dict]) -> None:
        for item in items:
            if item["id"] == item_id:
                if name is not None and name.strip():
                    item["name"] = name.strip()
                if quantity is not None:
                    item["quantity"] = clamp_quantity(quantity)

    return _mutate(change)


def set_checked(item_id: str, checked: bool) -> Notice:
    """구매 완료 여부를 지정한다.

    값을 뒤집지(toggle) 않고 지정하는 이유: 오래 열어 둔 탭이
    다른 탭에서 이미 바뀐 상태를 다시 뒤집어 버리지 않게 하기 위해서다.
    """
    def change(items: list[dict]) -> None:
        for item in items:
            if item["id"] == item_id:
                item["checked"] = bool(checked)

    return _mutate(change)


def delete_item(item_id: str) -> Notice:
    """아이템 하나 삭제 (순번이 아니라 id 기준)."""
    return _mutate(lambda items: [i for i in items if i["id"] != item_id])


def delete_checked_items() -> Notice:
    """구매 완료로 체크된 아이템만 삭제."""
    return _mutate(lambda items: [i for i in items if not i["checked"]])


def delete_all_items() -> Notice:
    """모든 아이템 삭제."""
    return _mutate(lambda items: [])
