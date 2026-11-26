"""端到端业务场景测试（不依赖 pytest/httpx，直接用内存 store 驱动领域服务与路由函数）。

覆盖题面场景：
1. CUS 变更生效只通知真实订阅 CUS 的 A/B，XCUS 订阅方不会被相同编码片段误命中；
2. 通知携带同一实体与真实生效版本，驳回/未生效变更不产生可消费通知；
3. 同实体同版本重复投递只生成一条、只确认一次；
4. A 改订 XCUS 后迟到的 CUS 通知产生订阅归属冲突，A 只能拒收，且保留拒收原因；
5. B 仍有 CUS 有效订阅，可接管在途通知并拿到 CUS v3 刷新回执；
6. 值班员从原通知跟进，可查看订阅变化关闭或接管确认；
7. 审批单可查生效回执，XCUS 版本数据不受 CUS 变更影响；
8. 刷新回执可回查原通知依据，依据核对通过；
9. 实际刷新实体/版本与通知不一致时被拒收。
"""
from __future__ import annotations

import pathlib
import sys

# 隔离模式（python -I）下不会把 cwd 加入 sys.path，显式补上后端根目录。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.seed import SEED_ROWS
from app.store import store
from app.services import service_for
from app.services.domain import (
    NOTICE_CLOSED,
    NOTICE_CONFIRMED,
    NOTICE_PENDING,
    NOTICE_REJECTED,
    RECEIPT_CONFIRMED,
    RECEIPT_REJECTED,
    split_subscribed_entities,
    subscription_covers,
)
from app.routers import workflow as workflow_router

# ---- 构造干净场景数据 ----

def reset_scenario() -> None:
    store._tables = {name: [dict(r) for r in rows] for name, rows in SEED_ROWS.items()}
    store._tables["change_notification"] = []
    store._tables["refresh_receipt"] = []

    models = store.rows("entity_model")
    models.clear()
    models.append({"id": 1, "status": "已发布", "pending": False, "abnormal": False,
                   "实体编码": "CUS", "实体名称": "客户主数据", "唯一键规则": "cust_id",
                   "合并策略": "最新优先", "版本号": "v2"})
    models.append({"id": 2, "status": "已发布", "pending": False, "abnormal": False,
                   "实体编码": "XCUS", "实体名称": "扩展客户主数据", "唯一键规则": "xcust_id",
                   "合并策略": "最新优先", "版本号": "v9"})

    subs = store.rows("subscriber_mgr")
    subs.clear()
    # A：先订阅 CUS；C：订阅 XCUS（编码片段与 CUS 有相同子串）
    subs.append({"id": 1, "status": "已生效", "pending": False, "abnormal": False,
                 "订阅方标识": "A", "订阅实体": "CUS", "分发格式": "JSON",
                 "订阅过滤": "", "生效状态": "已生效"})
    subs.append({"id": 2, "status": "已生效", "pending": False, "abnormal": False,
                 "订阅方标识": "B", "订阅实体": "CUS,ENT", "分发格式": "JSON",
                 "订阅过滤": "", "生效状态": "已生效"})
    subs.append({"id": 3, "status": "已生效", "pending": False, "abnormal": False,
                 "订阅方标识": "C", "订阅实体": "XCUS", "分发格式": "JSON",
                 "订阅过滤": "", "生效状态": "已生效"})

    changes = store.rows("model_change")
    changes.clear()
    # 1: 待生效的 CUS v3；2: 被驳回的 CUS 变更；3: 已起草未提交
    changes.append({"id": 1, "status": "待审批", "pending": True, "abnormal": False,
                    "变更单号": "MC-CUS-3", "实体编码": "CUS", "变更内容": "新增客户等级字段",
                    "审批状态": "待审批", "生效版本": "v3"})
    changes.append({"id": 2, "status": "待审批", "pending": True, "abnormal": False,
                    "变更单号": "MC-CUS-X", "实体编码": "CUS", "变更内容": "不合规变更",
                    "审批状态": "待审批", "生效版本": "v4"})
    changes.append({"id": 3, "status": "起草中", "pending": True, "abnormal": False,
                    "变更单号": "MC-CUS-D", "实体编码": "CUS", "变更内容": "草稿变更",
                    "审批状态": "起草中", "生效版本": "v5"})


mc = service_for("model_change")
sub_svc = service_for("subscriber_mgr")
cn_svc = service_for("change_notification")
rr_svc = service_for("refresh_receipt")

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  ✓ {name}")
    else:
        failures.append(f"{name} {detail}")
        print(f"  ✗ {name} {detail}")


# ---- 测试开始 ----

reset_scenario()

print("1. 精确订阅匹配：CUS 不会命中 XCUS")
check("订阅实体拆分", split_subscribed_entities("CUS,ENT") == ["CUS", "ENT"])
check("CUS 覆盖 CUS", subscription_covers("CUS", "CUS") is True)
check("XCUS 不覆盖 CUS（子串隔离）", subscription_covers("XCUS", "CUS") is False)
check("CUS 不覆盖 XCUS（子串隔离）", subscription_covers("CUS", "XCUS") is False)
check("多值订阅精确命中", subscription_covers("CUS, ENT", "ENT") is True)
check("无关编码不命中", subscription_covers("CUS,ENT", "XCUS") is False)

print("2. 驳回 / 未生效变更不能产生可消费通知")
r = mc.dispatch_change_notifications(3)  # 起草中
check("起草中通知被拒", r["ok"] is False)
mc.reject_with_reason(2, "审批不通过")
r = mc.dispatch_change_notifications(2)  # 已驳回
check("驳回通知被拒", r["ok"] is False and r["notified"] == [])
check("驳回后无通知落库", store.rows("change_notification") == [])

print("3. CUS v3 生效：只通知 A/B，不通知订阅 XCUS 的 C")
r = mc.apply_effective_version(1)
check("生效成功", r["ok"] is True and r["version"] == "v3")
check("实体版本回写 v3", next(m for m in store.rows("entity_model") if m["实体编码"] == "CUS")["版本号"] == "v3")
notices = store.rows("change_notification")
check("只生成 A/B 两条通知",
      sorted(n["订阅方标识"] for n in notices) == ["A", "B"],
      str([(n["订阅方标识"], n["实体编码"], n["生效版本"]) for n in notices]))
check("C（XCUS）未被通知", all(n["订阅方标识"] != "C" for n in notices))
check("通知携带同一实体与真实版本",
      all(n["实体编码"] == "CUS" and n["生效版本"] == "v3" and n["变更单号"] == "MC-CUS-3"
          for n in notices))
check("通知均为待处理", all(n["通知状态"] == NOTICE_PENDING for n in notices))
notice_a = next(n for n in notices if n["订阅方标识"] == "A")
notice_b = next(n for n in notices if n["订阅方标识"] == "B")

print("4. 重复投递相同实体与版本：只保留一条")
r = mc.dispatch_change_notifications(1)
check("重复投递幂等", r["ok"] is True and r["notified"] == [] and
      sorted(r["skipped"]) == ["A", "B"])
check("通知总数仍为 2", len(store.rows("change_notification")) == 2)

print("5. 变更通知模块列表按实际订阅关系展示，XCUS 无操作入口数据")
items, total = cn_svc.list_entries()
check("通知列表 2 条", total == 2)
check("列表标注当前订阅覆盖", all(i["当前订阅覆盖"] is True for i in items))
check("通知模块无 XCUS 数据", all(i["实体编码"] != "XCUS" for i in items))

print("6. A 在首次刷新前改订 XCUS，迟到旧通知出现归属冲突")
r = sub_svc.change_subscription(1, "XCUS")
check("改订成功", r["ok"] is True and r["订阅实体"] == ["XCUS"])
a_row = store.find("subscriber_mgr", 1)
check("A 当前订阅为 XCUS", split_subscribed_entities(a_row["订阅实体"]) == ["XCUS"])
inbox = sub_svc.list_inbox_notifications(1)
check("A 的接收入口仍能看到原 CUS 通知", len(inbox) == 1 and inbox[0]["id"] == notice_a["id"])
check("通知被标注为订阅不再覆盖", inbox[0]["当前订阅覆盖"] is False)

print("7. A 尝试确认刷新：因订阅归属冲突被拒收，保留拒收原因")
r = sub_svc.confirm_refresh(1, notice_a["id"])
check("A 确认被拒收", r["ok"] is False and r["notice"]["通知状态"] == NOTICE_REJECTED)
check("生成拒收回执", r["receipt"]["回执状态"] == RECEIPT_REJECTED and "不再覆盖" in r["receipt"]["拒收原因"])
check("A 保留拒收原因", bool(store.find("subscriber_mgr", 1).get("拒收原因")))
# 重复办理同一条通知
r2 = sub_svc.confirm_refresh(1, notice_a["id"])
check("已办结通知不能重复办理", r2["ok"] is False and "不能重复办理" in r2["message"])

print("8. 值班员从原 CUS 通知跟进 A 的通知")
fu = mc.follow_up_notification(notice_a["id"])
check("跟进可见订阅已不覆盖", fu["ok"] is True and fu["subscription_still_covers"] is False)
check("跟进可见拒收结论", "拒收" in fu["notice"]["处理结论"])
# 已拒收的通知不能再以订阅变化关闭
r = mc.close_notice_for_subscription_change(notice_a["id"])
check("已办结通知不能关闭", r["ok"] is False)

print("9. B 仍有 CUS 有效订阅，接管另一条在途通知并确认刷新")
check("B 订阅仍覆盖 CUS", subscription_covers(store.find("subscriber_mgr", 2)["订阅实体"], "CUS") is True)
# 路由层 handover 走一遍
resp = workflow_router.handover_notice(notice_b["id"], workflow_router.HandoverPayload(takeover_subscriber="B"))
check("B 接管成功", resp.ok is True)
b_row = store.find("subscriber_mgr", 2)
check("B 保留最后实际使用版本", b_row.get("最后刷新实体") == "CUS" and b_row.get("最后刷新版本") == "v3")
receipts = store.rows("refresh_receipt")
b_receipt = next(r for r in receipts if r["订阅方标识"] == "B")
check("B 拿到 CUS v3 刷新回执",
      b_receipt["回执状态"] == RECEIPT_CONFIRMED and b_receipt["实体编码"] == "CUS"
      and b_receipt["生效版本"] == "v3")
notice_b_after = next(n for n in store.rows("change_notification") if n["id"] == notice_b["id"])
check("B 的通知已关闭并关联回执",
      notice_b_after["通知状态"] == NOTICE_CLOSED and notice_b_after["关联回执id"] == b_receipt["id"])

print("10. 无资格订阅方不能接管（XCUS 的 C 不能接 CUS 的通知）")
# 再造一条待处理通知用于负例：新版本 v3.1 的已生效变更单
changes = store.rows("model_change")
changes.append({"id": 4, "status": "待审批", "pending": True, "abnormal": False,
                "变更单号": "MC-CUS-3B", "实体编码": "CUS", "变更内容": "再次变更",
                "审批状态": "待审批", "生效版本": "v3.1"})
mc.apply_effective_version(4)
notice_extra = next(n for n in store.rows("change_notification") if n["变更单id"] == 4 and n["订阅方标识"] == "B")
check("新版本生成新通知", notice_extra["生效版本"] == "v3.1")
r = mc.handover_notice(notice_extra["id"], "C")
check("XCUS 订阅方接管 CUS 通知被拒", r["ok"] is False and "不覆盖实体" in r["message"])
r = mc.handover_notice(notice_extra["id"], "NOT-EXIST")
check("不存在订阅方接管被拒", r["ok"] is False)

print("11. 审批单可查生效回执；通知统计正确")
detail = mc.get_entry(1)
check("审批单附带通知", len(detail["变更通知"]) == 2)
check("通知统计", detail["通知统计"] == {"待处理": 0, "已确认": 0, "已拒收": 1, "已关闭": 1},
      str(detail["通知统计"]))
check("审批单生效回执含 B 的 CUS v3",
      len(detail["生效回执"]) == 1 and detail["生效回执"][0]["订阅方标识"] == "B")

print("12. 刷新回执回查原通知依据 + 依据核对")
basis = sub_svc.lookup_receipt_basis(2, b_receipt["id"])
check("回执回查到通知与变更单",
      basis["ok"] is True and basis["notice"]["实体编码"] == "CUS"
      and basis["change_order"]["生效版本"] == "v3"
      and basis["change_order"]["审批状态"] == "已生效")
verify = rr_svc.verify_basis(b_receipt["id"])
check("回执依据核对通过", verify["ok"] is True)
# A 不能回查 B 的回执
check("跨订阅方回查被拒", sub_svc.lookup_receipt_basis(1, b_receipt["id"])["ok"] is False)

print("13. 实际刷新实体/版本与通知不一致被拒收；依据正确时确认且只确认一次")
# B 的新通知（v3）尝试按 XCUS/v9 确认 → 拒收（拒收为终态）
r = sub_svc.confirm_refresh(2, notice_extra["id"], refreshed_entity="XCUS", refreshed_version="v9")
check("错实体错版本确认被拒收", r["ok"] is False and "不一致" in r["message"])
check("拒收依据落回执", r["receipt"]["回执状态"] == RECEIPT_REJECTED)
# 再造一条 B 的在途通知用于正确确认
changes.append({"id": 5, "status": "待审批", "pending": True, "abnormal": False,
                "变更单号": "MC-CUS-3C", "实体编码": "CUS", "变更内容": "第三次变更",
                "审批状态": "待审批", "生效版本": "v3.2"})
mc.apply_effective_version(5)
notice_b3 = next(n for n in store.rows("change_notification")
                 if n["变更单id"] == 5 and n["订阅方标识"] == "B")
r = sub_svc.confirm_refresh(2, notice_b3["id"])
check("按通知依据确认成功", r["ok"] is True and r["receipt"]["回执状态"] == RECEIPT_CONFIRMED)
check("B 最后使用版本更新为 CUS v3.2",
      store.find("subscriber_mgr", 2).get("最后刷新实体") == "CUS"
      and store.find("subscriber_mgr", 2).get("最后刷新版本") == "v3.2")
r = sub_svc.confirm_refresh(2, notice_b3["id"])
check("重复确认只生效一次", r["ok"] is False and "不能重复办理" in r["message"])

print("14. 订阅变化关闭路径（尚未拒收的在途通知）")
# 新增 A 订阅 CUS 的通知，再改订，由值班员关闭
changes.append({"id": 6, "status": "待审批", "pending": True, "abnormal": False,
                "变更单号": "MC-CUS-6", "实体编码": "CUS", "变更内容": "又一次变更",
                "审批状态": "待审批", "生效版本": "v6"})
# 让 A 临时重新订阅 CUS 以便收到通知
sub_svc.change_subscription(1, "CUS")
mc.apply_effective_version(6)
notice_a2 = next(n for n in store.rows("change_notification") if n["变更单id"] == 6 and n["订阅方标识"] == "A")
sub_svc.change_subscription(1, "XCUS")
r = mc.close_notice_for_subscription_change(notice_a2["id"])
check("订阅变化关闭成功", r["ok"] is True and r["notice"]["通知状态"] == NOTICE_CLOSED)
check("关闭原因记录订阅变化", "订阅变化关闭" in r["notice"]["处理结论"])
# 仍覆盖时不能关闭（B 仍订阅 CUS，其在途通知不能按订阅变化关闭）
b_pending = next(n for n in store.rows("change_notification")
                 if n["订阅方标识"] == "B" and n["通知状态"] == NOTICE_PENDING)
r = mc.close_notice_for_subscription_change(b_pending["id"])
check("仍订阅该实体时不能按订阅变化关闭", r["ok"] is False)

print("15. XCUS 版本数据不受 CUS 变更影响")
xcus = next(m for m in store.rows("entity_model") if m["实体编码"] == "XCUS")
check("XCUS 版本保持 v9", xcus["版本号"] == "v9")
check("XCUS 无任何 CUS 通知", all(n["实体编码"] != "XCUS" for n in store.rows("change_notification")))

print("16. 工作流路由端到端（订阅方接收入口 process + 审批单通知列表）")
# 走路由函数：dispatch 幂等
resp = workflow_router.dispatch_notifications(1)
check("路由 dispatch 幂等返回", resp.ok is True and resp.entry["notified"] == [])
resp = workflow_router.list_change_notices(1)
check("路由可查审批单通知与回执", len(resp["items"]) == 2 and len(resp["receipts"]) == 1)
resp = workflow_router.subscriber_inbox(3)
check("C（XCUS）接收入口无 CUS 通知", resp["items"] == [])

print()
if failures:
    print(f"失败 {len(failures)} 项：")
    for f in failures:
        print(" -", f)
    sys.exit(1)
print("全部场景测试通过 ✅")
