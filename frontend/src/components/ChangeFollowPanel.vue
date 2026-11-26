<template>
  <div class="workflow-panel" data-testid="change-follow-panel">
    <div class="notice-head">
      <div>
        <strong>{{ change.变更单号 }}</strong>
        <span class="page-desc">（{{ change.实体编码 }} · 生效版本 {{ change.生效版本 || '—' }} · {{ change.status }}</span>
      </div>
      <button class="btn" type="button" data-testid="redispatch-notice" @click="redispatch">
        重新投递通知
      </button>
    </div>

    <p class="page-desc">
      通知严格按订阅实体编码片段精确匹配：CUS 的变更不会投递给订阅 XCUS 的订阅方。
      重复投递相同实体与版本只确认一次。
    </p>

    <h4 class="section-title">变更通知（{{ notices.length }}）</h4>
    <article
      v-for="notice in notices"
      :key="notice.id"
      class="notice-card"
      :class="{ muted: notice.通知状态 !== '待处理' }"
      :data-testid="`notice-card-${notice.id}`"
    >
      <div class="notice-head">
        <span class="notice-title">{{ notice.通知编号 }} → {{ notice.订阅方标识 }}</span>
        <span class="badge" :class="statusClass(notice.通知状态)">{{ notice.通知状态 }}</span>
      </div>
      <div class="notice-meta">
        <span class="badge info">{{ notice.实体编码 }} @ {{ notice.生效版本 }}</span>
        <span
          class="badge"
          :class="covers(notice) ? 'ok' : 'bad'"
          :data-testid="`cover-${notice.id}`"
        >
          当前订阅{{ covers(notice) ? '仍覆盖' : '已不覆盖' }}
          <template v-if="notice.当前订阅实体?.length">（{{ notice.当前订阅实体.join('、') }}）</template>
        </span>
      </div>
      <p v-if="notice.处理结论" class="page-desc">办理结论：{{ notice.处理结论 }}</p>

      <div v-if="notice.通知状态 === '待处理'" class="notice-actions">
        <button class="btn" type="button" @click="emit('follow', notice)">值班跟进</button>
        <button class="btn" type="button" @click="emit('close', notice)">按订阅变化关闭</button>
        <button class="btn primary" type="button" @click="emit('handover', notice)">
          交同组订阅方接管
        </button>
      </div>
    </article>
    <p v-if="!notices.length" class="empty-state">该变更单暂无变更通知</p>

    <h4 class="section-title">生效回执（{{ receipts.length }}）</h4>
    <table v-if="receipts.length" class="data-table">
      <thead>
        <tr><th>回执编号</th><th>订阅方</th><th>刷新实体</th><th>刷新版本</th><th>状态</th></tr>
      </thead>
      <tbody>
        <tr v-for="receipt in receipts" :key="receipt.id" :data-testid="`effect-receipt-${receipt.id}`">
          <td>{{ receipt.回执编号 }}</td>
          <td>{{ receipt.订阅方标识 }}</td>
          <td>{{ receipt.刷新实体 }}</td>
          <td>{{ receipt.刷新版本 }}</td>
          <td><span class="badge ok">{{ receipt.回执状态 }}</span></td>
        </tr>
      </tbody>
    </table>
    <p v-else class="empty-state">暂无生效刷新回执</p>
  </div>
</template>

<script setup lang="ts">
import type { ChangeNotice, RefreshReceipt } from '@/api/workflow-service'
import type { EntryRow } from '@/data/types'

defineProps<{
  change: EntryRow
  notices: ChangeNotice[]
  receipts: RefreshReceipt[]
}>()

const emit = defineEmits<{
  (e: 'follow', notice: ChangeNotice): void
  (e: 'close', notice: ChangeNotice): void
  (e: 'handover', notice: ChangeNotice): void
  (e: 'redispatch'): void
}>()

function covers(notice: ChangeNotice): boolean {
  // 列表接口已按当前订阅关系标注；详情接口兜底用通知字段。
  return notice.当前订阅覆盖 ?? false
}

function statusClass(status: string): string {
  if (status === '已确认') return 'ok'
  if (status === '已拒收') return 'bad'
  if (status === '已关闭') return 'warn'
  return ''
}

function redispatch() {
  emit('redispatch')
}
</script>
