"""变更通知领域服务：管理实体变更生效后投递给下游订阅方的变更通知。

数据链路位置：模型治理层与分发层之间的通知通道，
每条通知都绑定同一个实体编码与真实生效版本，可回查变更审批单与刷新回执。
"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.domain import (
    NOTICE_PENDING,
    find_notice,
    split_subscribed_entities,
    subscription_covers,
)
from app.store import store


class ChangeNotificationService(BaseModuleService):
    MODULE = "change_notification"
    ENTITY = "变更通知"
    OPERATION_TERM = "跟进"
    LIST_FIELDS = [
        "通知编号", "变更单号", "实体编码", "生效版本",
        "订阅方标识", "通知状态", "处理结论",
    ]
    REQUIRED_FIELDS = ["通知编号", "实体编码", "生效版本", "订阅方标识"]
    STATUS_ORDER = ["待处理", "已确认", "已拒收", "已关闭"]
    ACTION_RULES: dict[str, str] = {}
    NEGATIVE_ACTIONS: list[str] = []

    def list_entries(self, *, filters=None, keyword=None, status=None, page=1, size=20):
        rows = list(store.rows(self.MODULE))
        for field, expected in (filters or {}).items():
            if field in self.LIST_FIELDS:
                rows = [
                    row for row in rows
                    if expected.casefold() in str(row.get(field, "")).casefold()
                ]
        if keyword:
            rows = [
                row for row in rows
                if keyword.casefold() in str(row.get("通知编号", "")).casefold()
            ]
        if status:
            rows = [row for row in rows if row.get("通知状态") == status]
        # 附上订阅方当前订阅是否仍覆盖通知实体，界面按实际订阅关系显示。
        enriched = []
        for row in rows:
            item = dict(row)
            sub = next(
                (s for s in store.rows("subscriber_mgr")
                 if str(s.get("订阅方标识", "")) == str(row.get("订阅方标识", ""))),
                None,
            )
            item["当前订阅实体"] = split_subscribed_entities(
                sub.get("订阅实体", "") if sub else ""
            )
            item["当前订阅覆盖"] = bool(
                sub and subscription_covers(sub.get("订阅实体", ""), row.get("实体编码", ""))
            )
            enriched.append(item)
        total = len(enriched)
        start = (page - 1) * size
        return enriched[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        notice = find_notice(store.rows(self.MODULE), entry_id)
        if notice is None:
            return None
        item = dict(notice)
        sub = next(
            (s for s in store.rows("subscriber_mgr")
             if str(s.get("订阅方标识", "")) == str(notice.get("订阅方标识", ""))),
            None,
        )
        item["当前订阅实体"] = split_subscribed_entities(
            sub.get("订阅实体", "") if sub else ""
        )
        item["当前订阅覆盖"] = bool(
            sub and subscription_covers(sub.get("订阅实体", ""), notice.get("实体编码", ""))
        )
        item["关联回执"] = next(
            (dict(r) for r in store.rows("refresh_receipt")
             if int(r.get("id", 0)) == int(notice.get("关联回执id") or 0)),
            None,
        )
        return item

    def pending_for_entity(self, entity_code: str) -> list[dict[str, Any]]:
        """某实体尚未办结的变更通知。"""
        return [
            dict(n) for n in store.rows(self.MODULE)
            if str(n.get("实体编码", "")).strip() == str(entity_code).strip()
            and n.get("通知状态") == NOTICE_PENDING
        ]
