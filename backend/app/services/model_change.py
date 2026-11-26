"""实体变更审批领域服务：管理实体模型变更单的起草、提交审批、生效与驳回。

数据链路位置：模型治理层流程端，负责消费实体定义的版本变更，
把生效版本回写给实体模型并按真实订阅关系通知下游。

通知口径（修复点）：
- 只通知订阅实体中**精确包含**该实体编码的订阅方，``CUS`` 不会误投递给订阅 ``XCUS`` 的人；
- 通知必须携带同一个实体编码与真实生效版本，可追溯回变更审批单；
- 驳回或尚未生效的变更不会产生可消费通知；
- 同一实体 + 同一生效版本 + 同一订阅方重复投递只保留一条、只确认一次；
- 审批页可跟进在途通知：由订阅变化关闭，或经同组有效订阅方接管确认拿到刷新回执。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.services.domain import (
    NOTICE_CLOSED,
    NOTICE_CONFIRMED,
    NOTICE_PENDING,
    NOTICE_REJECTED,
    RECEIPT_CONFIRMED,
    RECEIPT_REJECTED,
    find_notice,
    find_subscriber,
    notice_key,
    split_subscribed_entities,
    subscription_covers,
)
from app.store import store


class ModelChangeService(BaseModuleService):
    MODULE = "model_change"
    ENTITY = "变更单"
    OPERATION_TERM = "校验"
    LIST_FIELDS = ["变更单号", "实体编码", "变更内容", "审批状态", "生效版本"]
    REQUIRED_FIELDS = ["变更单号", "实体编码", "变更内容"]
    STATUS_ORDER = ["起草中", "待审批", "已生效", "已驳回"]
    ACTION_RULES = {"提交审批": "待审批", "生效变更": "已生效", "驳回变更": "已驳回"}
    NEGATIVE_ACTIONS = ["驳回变更"]

    # ---- 业务扩展：变更审批与版本生效 ----

    def submit_for_approval(self, entry_id: int) -> dict[str, Any]:
        """提交审批：校验实体存在且变更内容完整。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "变更单不存在"}
        entity_code = entry.get("实体编码", "")
        model = next((m for m in store.rows("entity_model")
                      if m.get("实体编码") == entity_code), None)
        if model is None:
            return {"ok": False, "message": f"实体 {entity_code} 不存在"}
        if not str(entry.get("变更内容", "")).strip():
            return {"ok": False, "message": "变更内容为空，不能提交"}
        entry["status"] = "待审批"
        entry["审批状态"] = "待审批"
        entry["pending"] = True
        return {"ok": True, "entity": entity_code}

    def apply_effective_version(self, entry_id: int) -> dict[str, Any]:
        """生效变更：把生效版本回写实体模型。

        只有处于待审批的变更单可以生效；生效后自动按真实订阅关系投递变更通知。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "变更单不存在"}
        if entry.get("status") != "待审批":
            return {"ok": False, "message": "变更单不在待审批状态"}
        entity_code = str(entry.get("实体编码", "")).strip()
        version = str(entry.get("生效版本", "")).strip() or "v1"
        for model in store.rows("entity_model"):
            if model.get("实体编码") == entity_code:
                model["版本号"] = version
                model["status"] = "已发布"
        entry["status"] = "已生效"
        entry["审批状态"] = "已生效"
        entry["生效版本"] = version
        entry["pending"] = False
        entry["abnormal"] = False
        # 生效即按真实订阅关系生成可追溯、幂等的变更通知。
        self.dispatch_change_notifications(entry_id)
        return {"ok": True, "version": version}

    def reject_with_reason(self, entry_id: int, reason: str) -> str:
        """驳回变更并记录驳回原因。驳回不会产生任何可消费通知。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return "变更单不存在"
        reason = str(reason or "").strip() or "未填写驳回原因"
        entry["status"] = "已驳回"
        entry["审批状态"] = "已驳回"
        entry["驳回原因"] = reason
        entry["abnormal"] = True
        entry["pending"] = False
        return f"变更单 {entry.get('变更单号')} 已驳回: {reason}"

    def consume_entity_versions(self, entry_id: int) -> list[str]:
        """读取实体模型的历史版本序列。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return []
        entity_code = entry.get("实体编码", "")
        return [m.get("版本号", "") for m in store.rows("entity_model")
                if m.get("实体编码") == entity_code]

    # ---- 变更通知：精确订阅匹配 + 实体/版本可追溯 + 幂等投递 ----

    def _active_entity_subscribers(self, entity_code: str) -> list[dict[str, Any]]:
        """返回订阅实体精确覆盖该实体编码的订阅方。

        先按多值分隔拆分「订阅实体」，再做完整片段相等比较，
        因此订阅 ``XCUS`` 的订阅方不会被 ``CUS`` 的变更命中。
        """
        matched: list[dict[str, Any]] = []
        for sub in store.rows("subscriber_mgr"):
            if subscription_covers(sub.get("订阅实体", ""), entity_code):
                matched.append(sub)
        return matched

    def dispatch_change_notifications(self, entry_id: int) -> dict[str, Any]:
        """为已生效变更单投递变更通知（幂等）。

        - 已驳回 / 尚未生效的变更不能进入可消费通知；
        - 仅投递给订阅关系精确覆盖该实体的订阅方；
        - 同一实体 + 同一生效版本 + 同一订阅方重复投递只生成一条；
        - 通知行携带变更单 id、实体编码、真实生效版本，可回查原依据。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "变更单不存在", "notified": [], "skipped": []}
        if entry.get("status") != "已生效":
            return {
                "ok": False,
                "message": "变更未生效，不能投递变更通知",
                "notified": [],
                "skipped": [],
            }
        entity_code = str(entry.get("实体编码", "")).strip()
        version = str(entry.get("生效版本", "")).strip()
        notices = store.rows("change_notification")
        existing_keys = {
            notice_key(n.get("实体编码", ""), n.get("生效版本", ""), n.get("订阅方标识", ""))
            for n in notices
        }
        now = datetime.now(timezone.utc).isoformat()
        created: list[dict[str, Any]] = []
        deduped: list[str] = []
        for sub in self._active_entity_subscribers(entity_code):
            subscriber = str(sub.get("订阅方标识", ""))
            key = notice_key(entity_code, version, subscriber)
            if key in existing_keys:
                # 重复投递：只确认一次，保留原通知，不再产生新待办。
                deduped.append(subscriber)
                continue
            notice_id = max((int(n.get("id", 0)) for n in notices), default=0) + 1
            notice = {
                "id": notice_id,
                "通知编号": f"CN-{entry_id}-{notice_id}",
                "变更单id": entry_id,
                "变更单号": entry.get("变更单号", ""),
                "实体编码": entity_code,
                "生效版本": version,
                "订阅方标识": subscriber,
                "通知状态": NOTICE_PENDING,
                "处理结论": "",
                "处理时间": "",
                "关联回执id": None,
                "创建时间": now,
                "status": NOTICE_PENDING,
                "pending": True,
                "abnormal": False,
            }
            notices.append(notice)
            existing_keys.add(key)
            created.append(notice)
        return {
            "ok": True,
            "message": f"变更 {entry.get('变更单号')} 的通知已按真实订阅关系投递",
            "notified": [n["订阅方标识"] for n in created],
            "skipped": deduped,
        }

    def notify_version_change(self, entry_id: int) -> list[str]:
        """版本生效后通知订阅该实体的订阅方刷新口径（保持兼容的返回形态）。"""
        result = self.dispatch_change_notifications(entry_id)
        if not result.get("ok"):
            return []
        return list(result["notified"])

    def list_change_notifications(self, entry_id: int) -> list[dict[str, Any]]:
        """打开审批单的在途/历史通知跟进列表，仅返回该变更单自己的通知。"""
        return [
            dict(n) for n in store.rows("change_notification")
            if int(n.get("变更单id", 0)) == int(entry_id)
        ]

    def get_effective_receipts(self, entry_id: int) -> list[dict[str, Any]]:
        """审批单可查的生效回执：本变更单下已确认的刷新回执。"""
        notice_ids = {
            int(n.get("id", 0)) for n in store.rows("change_notification")
            if int(n.get("变更单id", 0)) == int(entry_id)
        }
        return [
            dict(r) for r in store.rows("refresh_receipt")
            if int(r.get("通知id", 0)) in notice_ids
            and r.get("回执状态") == RECEIPT_CONFIRMED
        ]

    def follow_up_notification(self, notice_id: int) -> dict[str, Any]:
        """值班员从原 CUS 通知继续跟进：返回通知、订阅变化与回执归属。"""
        notice = find_notice(store.rows("change_notification"), notice_id)
        if notice is None:
            return {"ok": False, "message": "变更通知不存在"}
        sub = find_subscriber(notice.get("订阅方标识", ""))
        currently_covers = bool(
            sub and subscription_covers(sub.get("订阅实体", ""), notice.get("实体编码", ""))
        )
        receipt = None
        if notice.get("关联回执id"):
            receipt = next(
                (r for r in store.rows("refresh_receipt")
                 if int(r.get("id", 0)) == int(notice.get("关联回执id"))),
                None,
            )
        return {
            "ok": True,
            "notice": dict(notice),
            "current_subscription": split_subscribed_entities(
                sub.get("订阅实体", "") if sub else ""
            ),
            "subscription_still_covers": currently_covers,
            "receipt": dict(receipt) if receipt else None,
        }

    def close_notice_for_subscription_change(self, notice_id: int, reason: str = "") -> dict[str, Any]:
        """订阅方改订后不再覆盖原实体：以订阅变化为由关闭在途通知（关闭而非确认）。"""
        notice = find_notice(store.rows("change_notification"), notice_id)
        if notice is None:
            return {"ok": False, "message": "变更通知不存在"}
        if notice.get("通知状态") != NOTICE_PENDING:
            return {"ok": False, "message": f"通知已{notice.get('通知状态')}，不能关闭"}
        sub = find_subscriber(notice.get("订阅方标识", ""))
        covers = bool(
            sub and subscription_covers(sub.get("订阅实体", ""), notice.get("实体编码", ""))
        )
        if covers:
            return {"ok": False, "message": "订阅方当前仍订阅该实体，不能以订阅变化为由关闭"}
        detail = str(reason or "").strip() or (
            f"订阅方已改订 {split_subscribed_entities(sub.get('订阅实体', '')) if sub else []}，"
            f"不再覆盖实体 {notice.get('实体编码')}"
        )
        notice["通知状态"] = NOTICE_CLOSED
        notice["status"] = NOTICE_CLOSED
        notice["处理结论"] = f"订阅变化关闭：{detail}"
        notice["处理时间"] = datetime.now(timezone.utc).isoformat()
        notice["pending"] = False
        return {"ok": True, "message": "通知已按订阅变化关闭", "notice": dict(notice)}

    def handover_notice(self, notice_id: int, takeover_subscriber: str) -> dict[str, Any]:
        """同组仍持有有效订阅的订阅方接手尚未提交的版本刷新工作。

        校验接管方订阅关系精确覆盖通知实体，确认后生成 CUS 版本的刷新回执，
        原通知以接管确认关闭，回执回查原通知依据。
        """
        notice = find_notice(store.rows("change_notification"), notice_id)
        if notice is None:
            return {"ok": False, "message": "变更通知不存在"}
        if notice.get("通知状态") != NOTICE_PENDING:
            return {"ok": False, "message": f"通知已{notice.get('通知状态')}，不能接管"}
        takeover = find_subscriber(takeover_subscriber)
        if takeover is None:
            return {"ok": False, "message": f"订阅方 {takeover_subscriber} 不存在"}
        if not subscription_covers(takeover.get("订阅实体", ""), notice.get("实体编码", "")):
            return {
                "ok": False,
                "message": (
                    f"接管方 {takeover_subscriber} 的订阅 "
                    f"{split_subscribed_entities(takeover.get('订阅实体', ''))} 不覆盖实体 "
                    f"{notice.get('实体编码')}，不能接管"
                ),
            }
        entry = store.find(self.MODULE, int(notice.get("变更单id", 0)))
        if entry is None or entry.get("status") != "已生效":
            return {"ok": False, "message": "原变更未生效，不能接管刷新"}
        entity_code = str(notice.get("实体编码", "")).strip()
        version = str(notice.get("生效版本", "")).strip()
        receipts = store.rows("refresh_receipt")
        receipt_id = max((int(r.get("id", 0)) for r in receipts), default=0) + 1
        receipt = {
            "id": receipt_id,
            "回执编号": f"RR-{notice_id}-{receipt_id}",
            "通知id": int(notice.get("id", 0)),
            "通知编号": notice.get("通知编号", ""),
            "变更单号": notice.get("变更单号", ""),
            "实体编码": entity_code,
            "生效版本": version,
            "订阅方标识": takeover_subscriber,
            "回执状态": RECEIPT_CONFIRMED,
            "刷新实体": entity_code,
            "刷新版本": version,
            "拒收原因": "",
            "登记时间": datetime.now(timezone.utc).isoformat(),
            "status": RECEIPT_CONFIRMED,
            "pending": False,
            "abnormal": False,
        }
        receipts.append(receipt)
        notice["通知状态"] = NOTICE_CLOSED
        notice["status"] = NOTICE_CLOSED
        notice["处理结论"] = f"由 {takeover_subscriber} 接管确认"
        notice["处理时间"] = datetime.now(timezone.utc).isoformat()
        notice["关联回执id"] = receipt_id
        notice["pending"] = False
        takeover["最后刷新实体"] = entity_code
        takeover["最后刷新版本"] = version
        takeover["拒收原因"] = ""
        return {
            "ok": True,
            "message": f"{takeover_subscriber} 已接管并确认 {entity_code} {version} 的刷新",
            "notice": dict(notice),
            "receipt": receipt,
        }

    def register_change_lineage(self, entry_id: int) -> str | None:
        """登记变更单到实体模型血缘边。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        edges = store.rows("lineage_graph")
        edge_id = max((int(r.get("id", 0)) for r in edges), default=0) + 1
        edges.append({
            "id": edge_id,
            "血缘边标识": f"edge-change-{edge_id}",
            "上游节点": entry.get("变更单号", ""),
            "下游节点": entry.get("实体编码", ""),
            "变换规则": "变更生效",
            "登记时间": datetime.now(timezone.utc).isoformat(),
            "status": "已登记",
            "pending": False,
            "abnormal": False,
        })
        return f"edge-change-{edge_id}"

    # ---- 动作分派：状态流转仍集中在服务层，路由层不做业务判断 ----

    def run_action(self, entry_id: int, action: str, remark: str | None = None):
        if action == "生效变更":
            result = self.apply_effective_version(entry_id)
            entry = store.find(self.MODULE, entry_id)
            if not result.get("ok"):
                return None, result.get("message", "生效失败")
            return entry, f"变更已生效并完成通知投递"
        if action == "驳回变更":
            message = self.reject_with_reason(entry_id, str(remark or "审批不通过"))
            return store.find(self.MODULE, entry_id), message
        if action == "提交审批":
            result = self.submit_for_approval(entry_id)
            if not result.get("ok"):
                return None, result.get("message", "提交失败")
            return store.find(self.MODULE, entry_id), "变更单已提交审批"
        return super().run_action(entry_id, action)

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        """审批单详情附带通知跟进与生效回执，供审批页直接展示。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        detail = dict(entry)
        notices = self.list_change_notifications(entry_id)
        detail["变更通知"] = notices
        detail["通知统计"] = {
            "待处理": sum(1 for n in notices if n.get("通知状态") == NOTICE_PENDING),
            "已确认": sum(1 for n in notices if n.get("通知状态") == NOTICE_CONFIRMED),
            "已拒收": sum(1 for n in notices if n.get("通知状态") == NOTICE_REJECTED),
            "已关闭": sum(1 for n in notices if n.get("通知状态") == NOTICE_CLOSED),
        }
        detail["生效回执"] = self.get_effective_receipts(entry_id)
        return detail
