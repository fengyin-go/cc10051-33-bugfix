"""下游订阅方领域服务：管理下游系统对金记录版本的订阅关系、过滤条件与生效状态，完成导入动作。

数据链路位置：主数据分发层的消费端配置，负责消费发布版本，
按订阅过滤生成分发批次并衔接回执通道。

刷新确认口径（修复点）：
- 订阅实体按编码片段精确匹配，``CUS`` 与 ``XCUS`` 互不命中；
- 订阅方先把刷新请求与变更通知中的实际实体、版本关联，再确认或拒收；
- 确认会核对通知依据（同一实体 + 真实生效版本 + 变更单已生效），重复通知只确认一次；
- 改订后在途旧通知会因订阅不再覆盖而只能拒收/关闭，并保留拒收原因；
- 订阅方保留最后实际使用的刷新实体、版本与拒收原因。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.services.domain import (
    NOTICE_CONFIRMED,
    NOTICE_PENDING,
    NOTICE_REJECTED,
    RECEIPT_CONFIRMED,
    RECEIPT_REJECTED,
    find_change_order,
    find_notice,
    notice_key,
    split_subscribed_entities,
    subscription_covers,
)
from app.store import store


class SubscriberMgrService(BaseModuleService):
    MODULE = "subscriber_mgr"
    ENTITY = "订阅方"
    OPERATION_TERM = "导入"
    LIST_FIELDS = ["订阅方标识", "订阅实体", "分发格式", "订阅过滤", "生效状态"]
    REQUIRED_FIELDS = ["订阅方标识", "订阅实体", "分发格式"]
    STATUS_ORDER = ["待生效", "已生效", "已暂停"]
    ACTION_RULES = {"生效订阅": "已生效", "暂停订阅": "已暂停"}
    NEGATIVE_ACTIONS = []

    # ---- 业务扩展：订阅生效与分发过滤 ----

    def activate_subscription(self, entry_id: int) -> dict[str, Any]:
        """生效订阅并把订阅方加入分发名单。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "订阅方不存在"}
        if not str(entry.get("分发格式", "")).strip():
            return {"ok": False, "message": "分发格式缺失，不能生效"}
        entry["status"] = "已生效"
        entry["生效状态"] = "已生效"
        entry["pending"] = False
        return {"ok": True, "subscriber": entry.get("订阅方标识")}

    def apply_filter(self, entry_id: int, publish_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按订阅过滤条件筛选发布记录。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "已生效":
            return []
        cond = str(entry.get("订阅过滤", "")).strip()
        if not cond:
            return publish_rows
        field, _, expected = cond.partition("=")
        return [r for r in publish_rows if str(r.get(field, "")) == expected]

    def pause_and_recall(self, entry_id: int) -> dict[str, Any]:
        """暂停订阅并回收未送达的分发批次。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "订阅方不存在"}
        entry["status"] = "已暂停"
        entry["生效状态"] = "已暂停"
        entry["pending"] = True
        recalled = 0
        for task in store.rows("dist_task"):
            if task.get("订阅方") == entry.get("订阅方标识") and task.get("status") == "排队中":
                task["status"] = "分发失败"
                task["abnormal"] = True
                recalled += 1
        return {"ok": True, "recalled_tasks": recalled}

    def change_subscription(self, entry_id: int, new_entities: str) -> dict[str, Any]:
        """订阅方改订：更新订阅实体并记录改订时间。

        改订不删除在途通知，但旧通知会因订阅不再覆盖原实体而被识别为归属冲突，
        只能拒收或由值班员以订阅变化关闭 / 交同组订阅方接管。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "订阅方不存在"}
        entities = split_subscribed_entities(new_entities)
        if not entities:
            return {"ok": False, "message": "改订后的订阅实体为空"}
        # 先留存改订前的订阅关系，再写入新订阅，便于事后核对归属变化。
        entry["前次订阅实体"] = entry.get("订阅实体", "")
        entry["订阅实体"] = "，".join(entities)
        entry["改订时间"] = datetime.now(timezone.utc).isoformat()
        return {"ok": True, "subscriber": entry.get("订阅方标识"), "订阅实体": entities}

    def consume_publish_versions(self, entry_id: int) -> list[str]:
        """读取订阅实体的已发布版本列表（精确实体匹配，避免子串误命中）。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return []
        subscribed = split_subscribed_entities(entry.get("订阅实体", ""))
        versions: list[str] = []
        for p in store.rows("golden_publish"):
            if p.get("status") != "已发布":
                continue
            if str(p.get("实体编码", "")).strip() in subscribed:
                versions.append(p.get("版本标识", ""))
        return versions

    def produce_dist_batch(self, entry_id: int, version: str) -> int:
        """为订阅方生成分发批次，写入 dist_task。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return 0
        tasks = store.rows("dist_task")
        task_id = max((int(r.get("id", 0)) for r in tasks), default=0) + 1
        tasks.append({
            "id": task_id,
            "分发批次": f"dist-{entry.get('订阅方标识')}-{task_id}",
            "订阅方": entry.get("订阅方标识", ""),
            "记录范围": f"版本 {version}",
            "分发状态": "排队中",
            "回执状态": "未回收",
            "status": "排队中",
            "pending": True,
            "abnormal": False,
        })
        return task_id

    def ensure_receipt_collector(self, entry_id: int) -> dict[str, Any]:
        """确认订阅方回执通道可用，登记到回执中心。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "订阅方不存在"}
        receipts = store.rows("dist_receipt")
        receipt_id = max((int(r.get("id", 0)) for r in receipts), default=0) + 1
        receipts.append({
            "id": receipt_id,
            "回执编号": f"rc-{entry.get('订阅方标识')}-{receipt_id}",
            "分发批次": "",
            "订阅方": entry.get("订阅方标识", ""),
            "回执状态": "未回收",
            "差异说明": "通道注册",
            "status": "未回收",
            "pending": True,
            "abnormal": False,
        })
        return {"ok": True, "receipt_id": receipt_id}

    # ---- 变更通知接收入口：先关联实际实体与版本，再确认/拒收 ----

    def list_inbox_notifications(self, entry_id: int) -> list[dict[str, Any]]:
        """订阅方接收入口：列出派给本订阅方的变更通知，并标注当前订阅是否仍覆盖。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return []
        subscriber = str(entry.get("订阅方标识", ""))
        inbox: list[dict[str, Any]] = []
        for notice in store.rows("change_notification"):
            if str(notice.get("订阅方标识", "")) != subscriber:
                continue
            item = dict(notice)
            item["当前订阅覆盖"] = subscription_covers(
                entry.get("订阅实体", ""), notice.get("实体编码", "")
            )
            inbox.append(item)
        return inbox

    def _open_notice(self, entry: dict[str, Any], notice_id: int) -> tuple[dict[str, Any] | None, str]:
        notice = find_notice(store.rows("change_notification"), notice_id)
        if notice is None:
            return None, "变更通知不存在"
        if str(notice.get("订阅方标识", "")) != str(entry.get("订阅方标识", "")):
            return None, "通知不属于该订阅方，不能在其接收入口办理"
        if notice.get("通知状态") != NOTICE_PENDING:
            return None, f"通知已{notice.get('通知状态')}，不能重复办理"
        return notice, ""

    def _write_receipt(
        self,
        notice: dict[str, Any],
        subscriber: str,
        status: str,
        *,
        refreshed_entity: str,
        refreshed_version: str,
        reject_reason: str,
    ) -> dict[str, Any]:
        receipts = store.rows("refresh_receipt")
        receipt_id = max((int(r.get("id", 0)) for r in receipts), default=0) + 1
        receipt = {
            "id": receipt_id,
            "回执编号": f"RR-{notice.get('id')}-{receipt_id}",
            "通知id": int(notice.get("id", 0)),
            "通知编号": notice.get("通知编号", ""),
            "变更单号": notice.get("变更单号", ""),
            "实体编码": notice.get("实体编码", ""),
            "生效版本": notice.get("生效版本", ""),
            "订阅方标识": subscriber,
            "回执状态": status,
            "刷新实体": refreshed_entity,
            "刷新版本": refreshed_version,
            "拒收原因": reject_reason,
            "登记时间": datetime.now(timezone.utc).isoformat(),
            "status": status,
            "pending": status != RECEIPT_CONFIRMED,
            "abnormal": status == RECEIPT_REJECTED,
        }
        receipts.append(receipt)
        return receipt

    def confirm_refresh(self, entry_id: int, notice_id: int,
                        refreshed_entity: str = "", refreshed_version: str = "") -> dict[str, Any]:
        """确认刷新：把刷新请求与通知中的实际实体、版本关联后再确认。

        校验：
        - 通知属于本订阅方且仍待处理（重复通知只确认一次）；
        - 订阅方当前订阅仍精确覆盖通知实体（改订后不再覆盖则拒收）；
        - 通知依据的变更单仍为已生效，实体与版本与通知一致；
        - 实际刷新实体/版本必须等于通知携带的实体与真实生效版本。
        """
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "订阅方不存在"}
        notice, error = self._open_notice(entry, notice_id)
        if notice is None:
            return {"ok": False, "message": error}
        subscriber = str(entry.get("订阅方标识", ""))
        entity_code = str(notice.get("实体编码", "")).strip()
        version = str(notice.get("生效版本", "")).strip()

        if not subscription_covers(entry.get("订阅实体", ""), entity_code):
            reason = (
                f"订阅已变更为 {split_subscribed_entities(entry.get('订阅实体', ''))}，"
                f"不再覆盖通知实体 {entity_code}，拒绝刷新"
            )
            return self._reject(notice, entry, reason)

        change_order = find_change_order(int(notice.get("变更单id", 0)))
        if change_order is None or change_order.get("status") != "已生效":
            return self._reject(notice, entry, "通知依据的变更未生效或已驳回，不能消费")
        if str(change_order.get("实体编码", "")).strip() != entity_code or \
                str(change_order.get("生效版本", "")).strip() != version:
            return self._reject(notice, entry, "通知依据与变更单实际生效实体/版本不一致")

        actual_entity = str(refreshed_entity or "").strip() or entity_code
        actual_version = str(refreshed_version or "").strip() or version
        if actual_entity != entity_code or actual_version != version:
            return self._reject(
                notice, entry,
                f"实际刷新 {actual_entity}@{actual_version} 与通知依据 "
                f"{entity_code}@{version} 不一致",
            )

        receipt = self._write_receipt(
            notice, subscriber, RECEIPT_CONFIRMED,
            refreshed_entity=entity_code, refreshed_version=version, reject_reason="",
        )
        notice["通知状态"] = NOTICE_CONFIRMED
        notice["status"] = NOTICE_CONFIRMED
        notice["处理结论"] = f"{subscriber} 确认刷新 {entity_code}@{version}"
        notice["处理时间"] = datetime.now(timezone.utc).isoformat()
        notice["关联回执id"] = receipt["id"]
        notice["pending"] = False
        # 保留最后实际使用的版本。
        entry["最后刷新实体"] = entity_code
        entry["最后刷新版本"] = version
        entry["拒收原因"] = ""
        return {
            "ok": True,
            "message": f"{subscriber} 已确认刷新 {entity_code} {version}",
            "notice": dict(notice),
            "receipt": receipt,
        }

    def _reject(self, notice: dict[str, Any], entry: dict[str, Any], reason: str) -> dict[str, Any]:
        reason = str(reason or "").strip() or "订阅方拒收"
        subscriber = str(entry.get("订阅方标识", ""))
        receipt = self._write_receipt(
            notice, subscriber, RECEIPT_REJECTED,
            refreshed_entity="", refreshed_version="", reject_reason=reason,
        )
        notice["通知状态"] = NOTICE_REJECTED
        notice["status"] = NOTICE_REJECTED
        notice["处理结论"] = f"拒收：{reason}"
        notice["处理时间"] = datetime.now(timezone.utc).isoformat()
        notice["关联回执id"] = receipt["id"]
        notice["pending"] = False
        notice["abnormal"] = True
        entry["拒收原因"] = reason
        return {
            "ok": False,
            "message": reason,
            "notice": dict(notice),
            "receipt": receipt,
        }

    def reject_refresh(self, entry_id: int, notice_id: int, reason: str) -> dict[str, Any]:
        """拒收在途通知并记录拒收依据（如改订后订阅归属冲突）。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "订阅方不存在"}
        notice, error = self._open_notice(entry, notice_id)
        if notice is None:
            return {"ok": False, "message": error}
        return self._reject(notice, entry, reason)

    def process_notification(self, entry_id: int, notice_id: int, decision: str,
                             reason: str = "", refreshed_entity: str = "",
                             refreshed_version: str = "") -> dict[str, Any]:
        """接收入口统一办理：confirm / reject。"""
        if decision == "confirm":
            return self.confirm_refresh(entry_id, notice_id, refreshed_entity, refreshed_version)
        if decision == "reject":
            return self.reject_refresh(entry_id, notice_id, reason)
        return {"ok": False, "message": f"未知办理结论 {decision}"}

    def lookup_receipt_basis(self, entry_id: int, receipt_id: int) -> dict[str, Any]:
        """下游刷新回执回查原通知依据。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "订阅方不存在"}
        receipt = next((r for r in store.rows("refresh_receipt")
                        if int(r.get("id", 0)) == int(receipt_id)), None)
        if receipt is None:
            return {"ok": False, "message": "刷新回执不存在"}
        if str(receipt.get("订阅方标识", "")) != str(entry.get("订阅方标识", "")):
            return {"ok": False, "message": "回执不属于该订阅方"}
        notice = find_notice(store.rows("change_notification"), int(receipt.get("通知id", 0)))
        change_order = None
        if notice is not None:
            change_order = find_change_order(int(notice.get("变更单id", 0)))
        return {
            "ok": True,
            "receipt": dict(receipt),
            "notice": dict(notice) if notice else None,
            "change_order": {
                "变更单号": change_order.get("变更单号"),
                "实体编码": change_order.get("实体编码"),
                "生效版本": change_order.get("生效版本"),
                "审批状态": change_order.get("审批状态"),
            } if change_order else None,
        }

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        """订阅方详情附在途通知与最后刷新信息，供订阅方页面展示实际归属。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return None
        detail = dict(entry)
        detail["在途通知"] = self.list_inbox_notifications(entry_id)
        detail["订阅实体片段"] = split_subscribed_entities(entry.get("订阅实体", ""))
        return detail
