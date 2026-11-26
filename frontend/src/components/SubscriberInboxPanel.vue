<template>
  <div class="workflow-panel" data-testid="subscriber-inbox-panel">
    <div class="notice-head">
      <div>
        <strong>{{ subscriber.订阅方标识 }}</strong>
        <span class="page-desc">
          （当前订阅：{{ subscribedEntities.join('、') || subscriber.订阅实体 || '—' }}）
        </span>
      </div>
      <button class="btn" type="button" data-testid="change-subscription" @click="emit('resubscribe')">
        改订订阅
      </button>
    </div>

    <dl class="detail-list" v-if="subscriber.最后刷新版本 || subscriber.拒收原因">
      <template v-if="subscriber.最后刷新版本">
        <dt>最后刷新实体</dt><dd>{{ subscriber.最后刷新实体 }}</dd>
        <dt>最后刷新版本</dt><dd>{{ subscriber.最后刷新版本 }}</dd>
      </template>
      <template v-if="subscriber.拒收原因">
        <dt>拒收原因</dt><dd class="error-text">{{ subscriber.拒收原因 }}</dd>
      </template>
    </dl>

    <h4 class="section-title">变更通知接收入口（{{ inbox.length }}）</h4>
    <p class="page-desc">
      确认前会把刷新请求与通知中的实际实体、版本关联核对；改订后不再覆盖的旧通知只能拒收。
    </p>

    <article
      v-for="notice in inbox"
      :key="notice.id"
      class="notice-card"
      :class="{ muted: notice.通知状态 !== '待处理' }"
      :data-testid="`inbox-card-${notice.id}`"
    >
      <div class="notice-head">
        <span class="notice-title">{{ notice.通知编号 }}（{{ notice.变更单号 }}）</span>
        <span class="badge" :class="statusClass(notice.通知状态)">{{ notice.通知状态 }}</span>
      </div>
      <div class="notice-meta">
        <span class="badge info">通知依据 {{ notice.实体编码 }} @ {{ notice.生效版本 }}</span>
        <span class="badge" :class="notice.当前订阅覆盖 ? 'ok' : 'bad'">
          当前订阅{{ notice.当前订阅覆盖 ? '覆盖该实体' : '不覆盖该实体' }}
        </span>
      </div>
      <p v-if="notice.处理结论" class="page-desc">办理结论：{{ notice.处理结论 }}</p>

      <div v-if="notice.通知状态 === '待处理'" class="notice-actions">
        <button
          class="btn primary"
          type="button"
          :data-testid="`confirm-${notice.id}`"
          @click="emit('confirm', notice)"
        >
          按通知依据确认刷新
        </button>
        <button
          class="btn"
          type="button"
          :data-testid="`reject-${notice.id}`"
          @click="emit('reject', notice)"
        >
          拒收并登记原因
        </button>
      </div>
    </article>
    <p v-if="!inbox.length" class="empty-state">当前没有派发给该订阅方的变更通知（无关实体不会出现操作入口）</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ChangeNotice } from '@/api/workflow-service'
import type { EntryRow } from '@/data/types'

const props = defineProps<{
  subscriber: EntryRow
  inbox: ChangeNotice[]
}>()

const subscribedEntities = computed<string[]>(() => {
  const raw = props.subscriber.订阅实体片段
  return Array.isArray(raw) ? (raw as string[]) : []
})

const emit = defineEmits<{
  (e: 'resubscribe'): void
  (e: 'confirm', notice: ChangeNotice): void
  (e: 'reject', notice: ChangeNotice): void
}>()

function statusClass(status: string): string {
  if (status === '已确认') return 'ok'
  if (status === '已拒收') return 'bad'
  if (status === '已关闭') return 'warn'
  return ''
}
</script>
