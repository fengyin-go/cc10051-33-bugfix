<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button
          v-if="!isReadOnlyModule"
          class="btn primary"
          data-testid="open-create"
          type="button"
          @click="openCreate"
        >
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <!-- 刷新回执中心：专用回执面板（带依据核对） -->
    <RefreshReceiptPanel
      v-if="meta.key === 'refresh_receipt'"
      :rows="receiptRows"
      @verify="openVerify"
    />

    <!-- 变更通知跟进：专用通知面板（只读列表 + 值班跟进入口） -->
    <div v-else-if="meta.key === 'change_notification'">
      <p class="page-desc">
        通知按真实订阅关系展示，标注订阅方当前订阅是否仍覆盖通知实体；具体办理从变更审批单或订阅方接收入口进入。
      </p>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in meta.fields" :key="column">{{ column }}</th>
            <th>当前订阅覆盖</th>
            <th>跟进</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`">
            <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
            <td>
              <span class="badge" :class="row.当前订阅覆盖 ? 'ok' : 'bad'">
                {{ row.当前订阅覆盖 ? '覆盖' : '不覆盖' }}
              </span>
            </td>
            <td class="row-actions">
              <button class="link" type="button" :data-testid="`follow-link-${row.id}`" @click="openFollowUp(Number(row.id))">
                跟进通知
              </button>
            </td>
          </tr>
          <tr v-if="!rows.length">
            <td :colspan="meta.fields.length + 2" class="empty-state">暂无变更通知</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 通用模块表格 -->
    <table v-else class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th v-if="meta.actions.length">可执行动作</th>
          <th v-if="hasWorkflow">通知跟进</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td v-if="meta.actions.length" class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
          <td v-if="hasWorkflow" class="row-actions">
            <button
              v-if="meta.key === 'model_change'"
              class="link"
              type="button"
              :data-testid="`open-follow-${row.id}`"
              @click="openChangeFollow(row)"
            >
              通知跟进
            </button>
            <button
              v-if="meta.key === 'subscriber_mgr'"
              class="link"
              type="button"
              :data-testid="`open-inbox-${row.id}`"
              @click="openInbox(row)"
            >
              通知接收入口
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <!-- 变更审批单：通知跟进行动面板 -->
    <div v-if="followPanel.open && followPanel.change" class="modal-backdrop" data-testid="follow-modal" @click.self="followPanel.open = false">
      <div class="modal modal-wide">
        <ChangeFollowPanel
          :change="followPanel.change"
          :notices="followPanel.notices"
          :receipts="followPanel.receipts"
          @follow="(n) => openFollowUp(n.id)"
          @close="(n) => openClose(n)"
          @handover="(n) => openHandover(n)"
          @redispatch="redispatchNotices"
        />
        <div class="page-actions">
          <button class="btn" type="button" @click="followPanel.open = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 订阅方：接收入口行动面板 -->
    <div v-if="inboxPanel.open && inboxPanel.subscriber" class="modal-backdrop" data-testid="inbox-modal" @click.self="inboxPanel.open = false">
      <div class="modal modal-wide">
        <SubscriberInboxPanel
          :subscriber="inboxPanel.subscriber"
          :inbox="inboxPanel.items"
          @resubscribe="openResubscribe"
          @confirm="(n) => openConfirm(n)"
          @reject="(n) => openReject(n)"
        />
        <div class="page-actions">
          <button class="btn" type="button" @click="inboxPanel.open = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 通用工作流弹窗：改订/拒收/接管/关闭/跟进/核对 -->
    <WorkflowModal
      ref="workflowModalRef"
      :open="workflowModal.open"
      :mode="workflowModal.mode"
      :title="workflowModal.title"
      :target-notice="workflowModal.notice"
      :followup="workflowModal.followup"
      :verify-result="workflowModal.verifyResult"
      @close="workflowModal.open = false"
      @submit="handleWorkflowSubmit"
    />

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'

import {
  createEntry,
  downloadEntries,
  listEntries,
  moduleMeta,
  runAction as applyAction,
} from '@/api/backend-service'
import {
  changeSubscription,
  closeNotice,
  confirmRefresh,
  dispatchNotifications,
  followUpNotice,
  handoverNotice,
  listChangeNotices,
  rejectRefresh,
  subscriberInbox,
  verifyReceipt,
  type ChangeNotice,
  type FollowUp,
  type RefreshReceipt,
} from '@/api/workflow-service'
import ChangeFollowPanel from '@/components/ChangeFollowPanel.vue'
import RefreshReceiptPanel from '@/components/RefreshReceiptPanel.vue'
import SubscriberInboxPanel from '@/components/SubscriberInboxPanel.vue'
import WorkflowModal, { type WorkflowMode } from '@/components/WorkflowModal.vue'
import type { EntryRow } from '@/data/types'

const props = defineProps<{ moduleKey: string }>()
const meta = moduleMeta(props.moduleKey)
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = meta.fields.slice(0, 3)
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})

const READ_ONLY_MODULES = new Set(['change_notification', 'refresh_receipt'])
const isReadOnlyModule = READ_ONLY_MODULES.has(meta.key)
const hasWorkflow = meta.key === 'model_change' || meta.key === 'subscriber_mgr'

const receiptRows = ref<RefreshReceipt[]>([])

const stats = computed(() => [
  { label: meta.metrics[0], value: total.value },
  { label: meta.metrics[1], value: rows.value.filter((row) => row.status === meta.statuses[1]).length },
  {
    label: meta.metrics[2],
    value: rows.value.filter((row) => String(row.status) === meta.statuses[meta.statuses.length - 1]).length,
  },
])
const statusSummary = computed(() =>
  meta.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

// ---- 工作流弹窗与面板状态 ----

const workflowModalRef = ref<InstanceType<typeof WorkflowModal> | null>(null)
const workflowModal = reactive<{
  open: boolean
  mode: WorkflowMode
  title: string
  notice: ChangeNotice | null
  followup: FollowUp | null
  verifyResult: { ok: boolean; message: string } | null
  contextId: number | null
}>({
  open: false,
  mode: 'followup',
  title: '',
  notice: null,
  followup: null,
  verifyResult: null,
  contextId: null,
})

const followPanel = reactive<{
  open: boolean
  change: EntryRow | null
  notices: ChangeNotice[]
  receipts: RefreshReceipt[]
}>({ open: false, change: null, notices: [], receipts: [] })

const inboxPanel = reactive<{
  open: boolean
  subscriber: EntryRow | null
  items: ChangeNotice[]
}>({ open: false, subscriber: null, items: [] })

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.fields.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  try {
    let remark: string | undefined
    // 驳回类动作要求登记拒收/驳回依据，便于后续审计与界面展示。
    if (action.includes('驳回')) {
      const reason = window.prompt(`请填写「${action}」原因（将作为驳回依据保留）`)
      if (reason === null) return
      remark = reason.trim() || undefined
    }
    const result = await applyAction(meta.key, Number(row.id), action, remark)
    if (!result.ok) throw new Error(result.message)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
    if (meta.key === 'refresh_receipt') {
      receiptRows.value = payload.items as unknown as RefreshReceipt[]
    }
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

// ---- 变更审批单：通知跟进 ----

async function openChangeFollow(row: EntryRow) {
  errorMessage.value = ''
  try {
    const data = await listChangeNotices(Number(row.id))
    followPanel.change = row
    followPanel.notices = data.items
    followPanel.receipts = data.receipts
    followPanel.open = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '通知跟进读取失败'
  }
}

async function redispatchNotices() {
  if (!followPanel.change) return
  errorMessage.value = ''
  try {
    const result = await dispatchNotifications(Number(followPanel.change.id))
    if (!result.ok) throw new Error(result.message)
    await openChangeFollow(followPanel.change)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重新投递失败'
  }
}

// ---- 订阅方接收入口 ----

async function openInbox(row: EntryRow) {
  errorMessage.value = ''
  try {
    const data = await subscriberInbox(Number(row.id))
    inboxPanel.subscriber = row
    inboxPanel.items = data.items
    inboxPanel.open = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '接收入口读取失败'
  }
}

// ---- 工作流弹窗打开方式 ----

async function openFollowUp(noticeId: number) {
  errorMessage.value = ''
  try {
    const data = await followUpNotice(noticeId)
    workflowModal.mode = 'followup'
    workflowModal.title = '变更通知跟进'
    workflowModal.notice = data.notice
    workflowModal.followup = data
    workflowModal.verifyResult = null
    workflowModal.contextId = noticeId
    workflowModal.open = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '跟进信息读取失败'
  }
}

function openResubscribe() {
  workflowModal.mode = 'resubscribe'
  workflowModal.title = '订阅方改订'
  workflowModal.notice = null
  workflowModal.followup = null
  workflowModal.verifyResult = null
  workflowModal.contextId = inboxPanel.subscriber ? Number(inboxPanel.subscriber.id) : null
  workflowModal.open = true
  workflowModalRef.value?.resetForm(inboxPanel.subscriber ? String(inboxPanel.subscriber.订阅实体 ?? '') : '')
}

function openReject(notice: ChangeNotice) {
  workflowModal.mode = 'reject'
  workflowModal.title = '拒收变更通知'
  workflowModal.notice = notice
  workflowModal.followup = null
  workflowModal.verifyResult = null
  workflowModal.contextId = inboxPanel.subscriber ? Number(inboxPanel.subscriber.id) : null
  workflowModal.open = true
  workflowModalRef.value?.resetForm('')
}

function openConfirm(notice: ChangeNotice) {
  // 确认动作无需弹窗表单，直接按通知携带的实体/版本提交；服务端会再核对依据。
  void handleConfirm(notice)
}

function openHandover(notice: ChangeNotice) {
  workflowModal.mode = 'handover'
  workflowModal.title = '同组订阅方接管刷新'
  workflowModal.notice = notice
  workflowModal.followup = null
  workflowModal.verifyResult = null
  workflowModal.contextId = null
  workflowModal.open = true
  workflowModalRef.value?.resetForm('')
}

function openClose(notice: ChangeNotice) {
  workflowModal.mode = 'close'
  workflowModal.title = '按订阅变化关闭通知'
  workflowModal.notice = notice
  workflowModal.followup = null
  workflowModal.verifyResult = null
  workflowModal.contextId = null
  workflowModal.open = true
  workflowModalRef.value?.resetForm('')
}

async function openVerify(receipt: RefreshReceipt) {
  errorMessage.value = ''
  try {
    const result = await verifyReceipt(Number(receipt.id))
    workflowModal.mode = 'verify'
    workflowModal.title = '刷新回执依据核对'
    workflowModal.notice = null
    workflowModal.followup = null
    workflowModal.verifyResult = result
    workflowModal.contextId = Number(receipt.id)
    workflowModal.open = true
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '回执核对失败'
  }
}

async function handleConfirm(notice: ChangeNotice) {
  if (!inboxPanel.subscriber) return
  errorMessage.value = ''
  try {
    const result = await confirmRefresh(Number(inboxPanel.subscriber.id), Number(notice.id))
    if (!result.ok) {
      errorMessage.value = result.message
    }
    await refreshInbox()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '刷新确认失败'
  }
}

async function refreshInbox() {
  if (!inboxPanel.subscriber) return
  const data = await subscriberInbox(Number(inboxPanel.subscriber.id))
  inboxPanel.items = data.items
  // 同步订阅方行上的最后刷新版本/拒收原因（列表重新加载后替换引用）。
  await reload()
  const fresh = rows.value.find((r) => r.id === inboxPanel.subscriber?.id)
  if (fresh) inboxPanel.subscriber = fresh
}

async function handleWorkflowSubmit(text: string) {
  errorMessage.value = ''
  try {
    let ok = true
    let message = ''
    if (workflowModal.mode === 'resubscribe' && workflowModal.contextId != null) {
      const result = await changeSubscription(workflowModal.contextId, text)
      ok = result.ok
      message = result.message
      if (ok) {
        workflowModal.open = false
        await refreshInbox()
      }
    } else if (workflowModal.mode === 'reject' && workflowModal.notice && workflowModal.contextId != null) {
      const result = await rejectRefresh(workflowModal.contextId, Number(workflowModal.notice.id), text)
      ok = result.ok
      message = result.message
      if (ok) {
        workflowModal.open = false
        await refreshInbox()
      }
    } else if (workflowModal.mode === 'handover' && workflowModal.notice) {
      const result = await handoverNotice(Number(workflowModal.notice.id), text)
      ok = result.ok
      message = result.message
      if (ok) {
        workflowModal.open = false
        followPanel.open = false
        await reload()
      }
    } else if (workflowModal.mode === 'close' && workflowModal.notice) {
      const result = await closeNotice(Number(workflowModal.notice.id), text)
      ok = result.ok
      message = result.message
      if (ok) {
        workflowModal.open = false
        followPanel.open = false
        await reload()
      }
    }
    if (!ok) {
      workflowModalRef.value?.setError(message || '操作未生效')
    }
  } catch (error) {
    workflowModalRef.value?.setError(error instanceof Error ? error.message : '工作流操作失败')
  }
}

onMounted(reload)
</script>
