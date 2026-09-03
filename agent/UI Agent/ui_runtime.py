from __future__ import annotations


def ensure_single_page_contract(payload: dict) -> None:
    """
    校验 UI Agent 当前平台合同。

    设计注释：
    平台当前仍然只承接“单页 UI 原型”这一种输出形态，
    但这里不能再把业务场景写死成五子棋。
    这个校验现在只做平台真正需要的结构约束，不再要求固定控件关键词。
    """

    pages = payload.get("pages") or []
    if len(pages) != 1:
        raise ValueError("Single-page UI must contain exactly one page.")

    page = pages[0]
    required_fields = ("page_id", "page_name", "purpose", "navigation", "layout", "artifacts")
    missing_fields = [field for field in required_fields if not page.get(field)]
    if missing_fields:
        raise ValueError(
            "Single-page UI requires non-empty fields: " + ", ".join(missing_fields)
        )

    artifacts = page.get("artifacts") or []
    if not isinstance(artifacts, list) or not any(str(item).strip() for item in artifacts):
        raise ValueError("Single-page UI requires at least one described page artifact.")
