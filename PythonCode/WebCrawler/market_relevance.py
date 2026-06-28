from __future__ import annotations

from typing import Any


WATER_PURIFIER_TERMS = (
    "\uc815\uc218\uae30",  # 정수기
    "\uc5bc\uc74c\uc815\uc218\uae30",  # 얼음정수기
    "\ub0c9\uc628\uc815\uc218\uae30",  # 냉온정수기
    "\ub0c9\uc815\uc218\uae30",  # 냉정수기
    "\uc628\uc815\uc218\uae30",  # 온정수기
    "\uc9c1\uc218\uc815\uc218\uae30",  # 직수정수기
    "\uc9c1\uc218\ud615",  # 직수형
    "\uc9c1\uc218",  # 직수
    "\uc815\uc218",  # 정수
    "water purifier",
    "water dispenser",
)

OTHER_PRODUCT_TERMS = (
    "\uc74c\uc2dd\ubb3c\ucc98\ub9ac\uae30",  # 음식물처리기
    "\uc74c\uc2dd\ubb3c \ucc98\ub9ac\uae30",  # 음식물 처리기
    "\uc74c\ucc98\uae30",  # 음처기
    "\ube44\ub370",  # 비데
    "\uacf5\uae30\uccad\uc815\uae30",  # 공기청정기
    "\uccad\uc815\uae30",  # 청정기
    "\uc778\ub355\uc158",  # 인덕션
    "\ub0c9\uc7a5\uace0",  # 냉장고
    "\ub0c9\ub3d9\uace0",  # 냉동고
    "\uc5d0\uc5b4\ucee8",  # 에어컨
    "\uc138\ud0c1\uae30",  # 세탁기
    "\uac74\uc870\uae30",  # 건조기
    "\ub9e4\ud2b8\ub9ac\uc2a4",  # 매트리스
    "\uc548\ub9c8\uc758\uc790",  # 안마의자
    "\uc11c\ud050\ub808\uc774\ud130",  # 서큘레이터
    "\uc120\ud48d\uae30",  # 선풍기
)


def is_water_purifier_market_text(*parts: Any) -> bool:
    text = joined_text(*parts)
    if not text:
        return False

    return any(term.lower() in text for term in WATER_PURIFIER_TERMS)


def is_clean_water_purifier_text(*parts: Any) -> bool:
    return is_water_purifier_market_text(*parts) and not has_other_product_signal(*parts)


def has_other_product_signal(*parts: Any) -> bool:
    text = joined_text(*parts)
    if not text:
        return False

    return any(term.lower() in text for term in OTHER_PRODUCT_TERMS)


def filter_clean_water_purifier_items(items: Any) -> list[str]:
    if items is None:
        return []
    if not isinstance(items, (list, tuple)):
        items = [items]

    result = []
    for item in items:
        text = str(item or "").strip()
        if text and is_clean_water_purifier_text(text):
            result.append(text)
    return result


def joined_text(*parts: Any) -> str:
    values: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, list):
            values.extend(str(item) for item in part if item is not None)
            continue
        if isinstance(part, tuple):
            values.extend(str(item) for item in part if item is not None)
            continue
        values.append(str(part))

    return "\n".join(values).lower()
