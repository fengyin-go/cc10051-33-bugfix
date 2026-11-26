"""变更通知领域共享逻辑：订阅实体精确匹配、通知与刷新回执的状态口径。

关键约束：
- 订阅实体是多值字段（可能用逗号/分号/竖线/空白分隔），必须按编码片段精确匹配，
  不能用子串包含，否则订阅 ``XCUS`` 的订阅方会被 ``CUS`` 的变更误命中。
- 通知、回执的状态与原因口径集中在这里，保证审批页、订阅方页和服务层一致。
"""
from __future__ import annotations

import re
from typing import Any

# 订阅实体多值分隔符：中英文逗号、分号、竖线、空白、顿号、斜杠等。
_SPLIT_RE = re.compile(r"[,，;；|/\s、]+")

# 通知处理状态
NOTICE_PENDING = "待处理"
NOTICE_CONFIRMED = "已确认"
NOTICE_REJECTED = "已拒收"
NOTICE_CLOSED = "已关闭"

# 刷新回执状态
RECEIPT_CONFIRMED = "已刷新"
RECEIPT_REJECTED = "已拒收"


def split_subscribed_entities(raw: Any) -> list[str]:
    """把订阅方的「订阅实体」字段拆成去重后的实体编码片段。"""
    if raw is None:
        return []
    seen: list[str] = []
    for token in _SPLIT_RE.split(str(raw)):
        code = token.strip()
        if code and code not in seen:
            seen.append(code)
    return seen


def subscription_covers(subscription_entities: Any, entity_code: str) -> bool:
    """判断订阅关系是否精确覆盖某个实体编码。

    必须命中拆分后的完整编码片段；``XCUS`` 与 ``CUS`` 互为不同片段，
    编码中相同的子串不会让两个订阅互相匹配。
    """
    target = str(entity_code or "").strip()
    if not target:
        return False
    return target in split_subscribed_entities(subscription_entities)


def notice_key(entity_code: str, version: str, subscriber: str) -> str:
    """同一实体 + 真实生效版本 + 同一订阅方的通知唯一键，用于重复投递去重。"""
    return f"{entity_code.strip()}::{str(version).strip()}::{subscriber.strip()}"


def find_notice(rows: list[dict[str, Any]], notice_id: int) -> dict[str, Any] | None:
    """按主键查找变更通知。"""
    for row in rows:
        if int(row.get("id", 0)) == int(notice_id):
            return row
    return None


def find_change_order(change_id: int) -> dict[str, Any] | None:
    """查找实体变更审批单。"""
    from app.store import store

    for row in store.rows("model_change"):
        if int(row.get("id", 0)) == int(change_id):
            return row
    return None


def find_subscriber(subscriber_id: str) -> dict[str, Any] | None:
    """按订阅方标识查找订阅方记录。"""
    from app.store import store

    for row in store.rows("subscriber_mgr"):
        if str(row.get("订阅方标识", "")) == str(subscriber_id):
            return row
    return None
