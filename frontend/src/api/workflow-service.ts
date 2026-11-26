/**
 * 变更通知工作流接口：对应后端 /api/workflow 路由。
 * 所有调用都围绕「变更单 → 变更通知 → 刷新回执」的真实订阅关系展开。
 */
import { request } from './client'
import type { ActionResult } from '@/data/types'

export type ChangeNotice = {
  id: number
  通知编号: string
  变更单id: number
  变更单号: string
  实体编码: string
  生效版本: string
  订阅方标识: string
  通知状态: string
  处理结论: string
  处理时间: string
  关联回执id: number | null
  当前订阅覆盖?: boolean
  当前订阅实体?: string[]
}

export type RefreshReceipt = {
  id: number
  回执编号: string
  通知编号: string
  变更单号: string
  实体编码: string
  生效版本: string
  订阅方标识: string
  回执状态: string
  刷新实体: string
  刷新版本: string
  拒收原因: string
}

async function postJson<T>(path: string, body: Record<string, unknown> = {}): Promise<T> {
  const response = await request(path, {
    method: 'POST',
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error('工作流接口请求失败')
  return (await response.json()) as T
}

async function getJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) throw new Error('工作流数据读取失败')
  return (await response.json()) as T
}

// ---- 实体变更审批：通知跟进 ----

export function dispatchNotifications(changeId: number): Promise<ActionResult> {
  return postJson(`/api/workflow/model-change/${changeId}/notifications/dispatch`)
}

export function listChangeNotices(
  changeId: number,
): Promise<{ items: ChangeNotice[]; receipts: RefreshReceipt[] }> {
  return getJson(`/api/workflow/model-change/${changeId}/notifications`)
}

export type FollowUp = {
  ok: boolean
  notice: ChangeNotice
  current_subscription: string[]
  subscription_still_covers: boolean
  receipt: RefreshReceipt | null
}

export function followUpNotice(noticeId: number): Promise<FollowUp> {
  return getJson(`/api/workflow/notifications/${noticeId}/follow-up`)
}

export function closeNotice(noticeId: number, reason = ''): Promise<ActionResult> {
  return postJson(`/api/workflow/notifications/${noticeId}/close`, { reason })
}

export function handoverNotice(
  noticeId: number,
  takeoverSubscriber: string,
): Promise<ActionResult> {
  return postJson(`/api/workflow/notifications/${noticeId}/handover`, {
    takeover_subscriber: takeoverSubscriber,
  })
}

// ---- 下游订阅方：改订、接收入口、刷新确认/拒收、回执回查 ----

export function changeSubscription(
  subscriberId: number,
  entities: string,
): Promise<ActionResult> {
  return postJson(`/api/workflow/subscribers/${subscriberId}/subscription`, { entities })
}

export function subscriberInbox(subscriberId: number): Promise<{ items: ChangeNotice[] }> {
  return getJson(`/api/workflow/subscribers/${subscriberId}/notifications`)
}

export function confirmRefresh(
  subscriberId: number,
  noticeId: number,
  refreshedEntity = '',
  refreshedVersion = '',
): Promise<ActionResult> {
  return postJson(
    `/api/workflow/subscribers/${subscriberId}/notifications/${noticeId}/confirm`,
    { refreshed_entity: refreshedEntity, refreshed_version: refreshedVersion },
  )
}

export function rejectRefresh(
  subscriberId: number,
  noticeId: number,
  reason: string,
): Promise<ActionResult> {
  return postJson(
    `/api/workflow/subscribers/${subscriberId}/notifications/${noticeId}/reject`,
    { reason },
  )
}

export function lookupReceiptBasis(
  subscriberId: number,
  receiptId: number,
): Promise<{
  ok: boolean
  message?: string
  receipt: RefreshReceipt
  notice: ChangeNotice | null
  change_order: {
    变更单号: string
    实体编码: string
    生效版本: string
    审批状态: string
  } | null
}> {
  return getJson(
    `/api/workflow/subscribers/${subscriberId}/receipts/${receiptId}/basis`,
  )
}

// ---- 刷新回执中心：依据核对 ----

export function verifyReceipt(
  receiptId: number,
): Promise<{ ok: boolean; message: string }> {
  return postJson(`/api/workflow/refresh-receipts/${receiptId}/verify`)
}
