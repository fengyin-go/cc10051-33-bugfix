"""变更通知与刷新回执工作流接口。

路由层只做参数透传与结果包装，所有业务判断（订阅精确匹配、通知幂等、
拒收依据、接管资格、回执核对）都在领域服务内完成。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.schemas import ActionResult
from app.services import service_for
from app.services.model_change import ModelChangeService
from app.services.refresh_receipt import RefreshReceiptService
from app.services.subscriber_mgr import SubscriberMgrService

router = APIRouter(prefix="/api/workflow", tags=["变更通知工作流"])


class NoticeDispatchPayload(BaseModel):
    pass


class RejectPayload(BaseModel):
    reason: str = ""


class ClosePayload(BaseModel):
    reason: str = ""


class HandoverPayload(BaseModel):
    takeover_subscriber: str


class ChangeSubscriptionPayload(BaseModel):
    entities: str


class RefreshConfirmPayload(BaseModel):
    refreshed_entity: str = ""
    refreshed_version: str = ""


class ProcessNoticePayload(BaseModel):
    decision: str
    reason: str = ""
    refreshed_entity: str = ""
    refreshed_version: str = ""


def _model_service() -> ModelChangeService:
    return service_for("model_change")  # type: ignore[return-value]


def _subscriber_service() -> SubscriberMgrService:
    return service_for("subscriber_mgr")  # type: ignore[return-value]


def _receipt_service() -> RefreshReceiptService:
    return service_for("refresh_receipt")  # type: ignore[return-value]


def _wrap(result: dict[str, Any]) -> ActionResult:
    notice = result.get("notice")
    receipt = result.get("receipt")
    return ActionResult(
        ok=bool(result.get("ok")),
        message=str(result.get("message", "")),
        entry=notice or receipt,
        data=result,
    )


# ---- 实体变更审批：通知跟进 ----

@router.post("/model-change/{change_id}/notifications/dispatch", response_model=ActionResult)
def dispatch_notifications(change_id: int) -> ActionResult:
    """（重新）投递变更通知：幂等，重复的同实体同版本通知只保留一条。"""
    result = _model_service().dispatch_change_notifications(change_id)
    return ActionResult(ok=bool(result.get("ok")), message=result.get("message", ""), entry=result)


@router.get("/model-change/{change_id}/notifications")
def list_change_notices(change_id: int) -> dict[str, Any]:
    """从审批单打开在途/历史通知，查看实际订阅归属与确认/拒收结论。"""
    service = _model_service()
    return {
        "items": service.list_change_notifications(change_id),
        "receipts": service.get_effective_receipts(change_id),
    }


@router.get("/notifications/{notice_id}/follow-up")
def follow_up_notice(notice_id: int) -> dict[str, Any]:
    """值班员从原通知继续跟进：当前订阅是否覆盖、回执归属与办理结论。"""
    return _model_service().follow_up_notification(notice_id)


@router.post("/notifications/{notice_id}/close", response_model=ActionResult)
def close_notice(notice_id: int, payload: ClosePayload) -> ActionResult:
    """以订阅变化为由关闭在途通知。"""
    return _wrap(_model_service().close_notice_for_subscription_change(notice_id, payload.reason))


@router.post("/notifications/{notice_id}/handover", response_model=ActionResult)
def handover_notice(notice_id: int, payload: HandoverPayload) -> ActionResult:
    """同组仍有有效订阅的订阅方接管刷新并生成刷新回执。"""
    return _wrap(_model_service().handover_notice(notice_id, payload.takeover_subscriber))


# ---- 下游订阅方：改订、接收入口办理与回执回查 ----

@router.post("/subscribers/{subscriber_id}/subscription", response_model=ActionResult)
def change_subscription(subscriber_id: int, payload: ChangeSubscriptionPayload) -> ActionResult:
    """订阅方改订（如 CUS 改订 XCUS）。"""
    return _wrap(_subscriber_service().change_subscription(subscriber_id, payload.entities))


@router.get("/subscribers/{subscriber_id}/notifications")
def subscriber_inbox(subscriber_id: int) -> dict[str, Any]:
    """订阅方接收入口：列出通知并标注当前订阅是否仍覆盖通知实体。"""
    return {"items": _subscriber_service().list_inbox_notifications(subscriber_id)}


@router.post("/subscribers/{subscriber_id}/notifications/{notice_id}/confirm",
             response_model=ActionResult)
def confirm_refresh(subscriber_id: int, notice_id: int,
                    payload: RefreshConfirmPayload) -> ActionResult:
    """关联通知中的实际实体与版本后确认刷新。"""
    return _wrap(_subscriber_service().confirm_refresh(
        subscriber_id, notice_id, payload.refreshed_entity, payload.refreshed_version))


@router.post("/subscribers/{subscriber_id}/notifications/{notice_id}/reject",
             response_model=ActionResult)
def reject_refresh(subscriber_id: int, notice_id: int, payload: RejectPayload) -> ActionResult:
    """拒收通知并保留拒收原因。"""
    return _wrap(_subscriber_service().reject_refresh(
        subscriber_id, notice_id, payload.reason))


@router.post("/subscribers/{subscriber_id}/notifications/{notice_id}/process",
             response_model=ActionResult)
def process_notification(subscriber_id: int, notice_id: int,
                         payload: ProcessNoticePayload) -> ActionResult:
    """接收入口统一办理：confirm / reject。"""
    return _wrap(_subscriber_service().process_notification(
        subscriber_id, notice_id, payload.decision, payload.reason,
        payload.refreshed_entity, payload.refreshed_version))


@router.get("/subscribers/{subscriber_id}/receipts/{receipt_id}/basis")
def receipt_basis(subscriber_id: int, receipt_id: int) -> dict[str, Any]:
    """刷新回执回查原通知依据。"""
    return _subscriber_service().lookup_receipt_basis(subscriber_id, receipt_id)


# ---- 刷新回执中心：依据核对 ----

@router.post("/refresh-receipts/{receipt_id}/verify")
def verify_receipt(receipt_id: int) -> dict[str, Any]:
    """核对回执实体/版本与通知、已生效变更单一致。"""
    return _receipt_service().verify_basis(receipt_id)
