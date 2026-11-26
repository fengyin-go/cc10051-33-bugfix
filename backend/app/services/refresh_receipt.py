"""刷新回执领域服务：订阅方针对变更通知的刷新确认与拒收回执。

数据链路位置：分发层对账端，每条回执都回链原变更通知（实体 + 真实生效版本 +
变更单），支持从回执反查通知依据，也供变更审批页查询生效回执。
"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.services.domain import find_change_order, find_notice
from app.store import store


class RefreshReceiptService(BaseModuleService):
    MODULE = "refresh_receipt"
    ENTITY = "刷新回执"
    OPERATION_TERM = "核对"
    LIST_FIELDS = [
        "回执编号", "通知编号", "变更单号", "实体编码", "生效版本",
        "订阅方标识", "回执状态", "刷新实体", "刷新版本", "拒收原因",
    ]
    REQUIRED_FIELDS = ["回执编号", "通知编号", "订阅方标识", "回执状态"]
    STATUS_ORDER = ["已刷新", "已拒收"]
    ACTION_RULES: dict[str, str] = {}
    NEGATIVE_ACTIONS: list[str] = []

    def list_entries(self, *, filters=None, keyword=None, status=None, page=1, size=20):
        rows = [dict(r) for r in store.rows(self.MODULE)]
        for field, expected in (filters or {}).items():
            if field in self.LIST_FIELDS:
                rows = [
                    row for row in rows
                    if expected.casefold() in str(row.get(field, "")).casefold()
                ]
        if keyword:
            rows = [
                row for row in rows
                if keyword.casefold() in str(row.get("回执编号", "")).casefold()
            ]
        if status:
            rows = [row for row in rows if row.get("回执状态") == status]
        total = len(rows)
        start = (page - 1) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        for row in store.rows(self.MODULE):
            if int(row.get("id", 0)) == int(entry_id):
                item = dict(row)
                notice = find_notice(
                    store.rows("change_notification"), int(row.get("通知id", 0))
                )
                item["原通知"] = dict(notice) if notice else None
                order = find_change_order(int(notice.get("变更单id", 0))) if notice else None
                item["原变更单"] = {
                    "变更单号": order.get("变更单号"),
                    "实体编码": order.get("实体编码"),
                    "生效版本": order.get("生效版本"),
                    "审批状态": order.get("审批状态"),
                } if order else None
                return item
        return None

    def verify_basis(self, entry_id: int) -> dict[str, Any]:
        """核对回执依据：回执的实体/版本必须与通知及已生效变更单一致。"""
        detail = self.get_entry(entry_id)
        if detail is None:
            return {"ok": False, "message": "刷新回执不存在"}
        notice = detail.get("原通知")
        order = detail.get("原变更单")
        if notice is None or order is None:
            return {"ok": False, "message": "回执缺少可追溯的通知或变更单依据"}
        entity = detail.get("实体编码")
        version = detail.get("生效版本")
        consistent = (
            notice.get("实体编码") == entity
            and notice.get("生效版本") == version
            and order.get("实体编码") == entity
            and order.get("生效版本") == version
            and order.get("审批状态") == "已生效"
        )
        return {
            "ok": bool(consistent),
            "message": "回执依据一致" if consistent else "回执依据与生效变更不一致",
            "receipt": detail,
        }
