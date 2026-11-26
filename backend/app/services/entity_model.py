"""主数据实体领域服务：管理实体定义的唯一键规则、合并策略、版本发布与废弃。

数据链路位置：主数据模型层，负责定义合并策略并向合并任务、清洗规则
派发生成规则，是金记录链路的规则来源。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class EntityModelService(BaseModuleService):
    MODULE = "entity_model"
    ENTITY = "实体定义"
    OPERATION_TERM = "合并"
    LIST_FIELDS = ["实体编码", "实体名称", "唯一键规则", "合并策略", "版本号"]
    REQUIRED_FIELDS = ["实体编码", "实体名称", "唯一键规则"]
    STATUS_ORDER = ["草稿", "已发布", "已废弃"]
    ACTION_RULES = {"发布实体": "已发布", "废弃实体": "已废弃"}
    NEGATIVE_ACTIONS = []

    # ---- 业务扩展：实体发布与合并策略联动 ----

    def publish_with_version(self, entry_id: int) -> dict[str, Any]:
        """发布实体定义并递增版本号，同步生成变更单。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return {"ok": False, "message": "实体定义不存在"}
        if entry.get("status") == "已废弃":
            return {"ok": False, "message": "已废弃实体不能发布"}
        old_ver = str(entry.get("版本号", "v0"))
        try:
            new_ver = f"v{int(old_ver.lstrip('v') or 0) + 1}"
        except ValueError:
            new_ver = old_ver
        entry["版本号"] = new_ver
        entry["status"] = "已发布"
        changes = store.rows("model_change")
        change_id = max((int(r.get("id", 0)) for r in changes), default=0) + 1
        changes.append({
            "id": change_id,
            "变更单号": f"MC-{entry_id}-{change_id}",
            "实体编码": entry.get("实体编码", ""),
            "变更内容": f"发布版本 {new_ver}",
            "审批状态": "已生效",
            "生效版本": new_ver,
            "status": "已生效",
            "pending": False,
            "abnormal": False,
        })
        # 已生效变更同样按真实订阅关系投递可追溯、幂等的变更通知。
        from app.services.model_change import ModelChangeService

        ModelChangeService().dispatch_change_notifications(change_id)
        return {"ok": True, "version": new_ver, "change_id": change_id}

    def spawn_merge_tasks(self, entry_id: int, candidate_groups: list[str]) -> list[int]:
        """按实体合并策略为候选组生成合并任务。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None or entry.get("status") != "已发布":
            return []
        tasks = store.rows("golden_merge")
        created: list[int] = []
        for group in candidate_groups:
            task_id = max((int(r.get("id", 0)) for r in tasks), default=0) + 1
            tasks.append({
                "id": task_id,
                "合并任务": f"merge-{entry.get('实体编码')}-{task_id}",
                "实体编码": entry.get("实体编码", ""),
                "候选组": group,
                "生还规则": entry.get("合并策略", "最新优先"),
                "合并结果": "",
                "status": "待合并",
                "pending": True,
                "abnormal": False,
            })
            created.append(task_id)
        return created

    def bind_cleanse_rules(self, entry_id: int, stages: list[str]) -> int:
        """为实体绑定标准化清洗规则，写入 std_cleanse。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return 0
        rules = store.rows("std_cleanse")
        count = 0
        for stage in stages:
            rule_id = max((int(r.get("id", 0)) for r in rules), default=0) + 1
            rules.append({
                "id": rule_id,
                "规则名称": f"cleanse-{entry.get('实体编码')}-{stage}",
                "实体编码": entry.get("实体编码", ""),
                "清洗阶段": stage,
                "规则表达式": "trim+upper",
                "异常处理": "转人工",
                "status": "草稿",
                "pending": True,
                "abnormal": False,
            })
            count += 1
        return count

    def consume_merge_results(self, entry_id: int) -> list[dict[str, Any]]:
        """读取合并任务产物，统计已完成合并数。"""
        code = (store.find(self.MODULE, entry_id) or {}).get("实体编码", "")
        return [r for r in store.rows("golden_merge")
                if r.get("实体编码") == code and r.get("status") == "已合并"]

    def request_change_approval(self, entry_id: int, content: str) -> str:
        """为实体发起模型变更审批单。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return "实体定义不存在"
        changes = store.rows("model_change")
        change_id = max((int(r.get("id", 0)) for r in changes), default=0) + 1
        changes.append({
            "id": change_id,
            "变更单号": f"MC-{entry_id}-{change_id}",
            "实体编码": entry.get("实体编码", ""),
            "变更内容": content,
            "审批状态": "待审批",
            "生效版本": entry.get("版本号", "v0"),
            "status": "待审批",
            "pending": True,
            "abnormal": False,
        })
        return f"MC-{entry_id}-{change_id}"

    def archive_deprecated(self, entry_id: int) -> str:
        """废弃实体并停止其清洗规则。"""
        entry = store.find(self.MODULE, entry_id)
        if entry is None:
            return "实体定义不存在"
        entry["status"] = "已废弃"
        for rule in store.rows("std_cleanse"):
            if rule.get("实体编码") == entry.get("实体编码") and rule.get("status") == "已启用":
                rule["status"] = "已停用"
                rule["abnormal"] = True
        return f"实体 {entry.get('实体编码')} 已废弃，关联清洗规则已停用"
