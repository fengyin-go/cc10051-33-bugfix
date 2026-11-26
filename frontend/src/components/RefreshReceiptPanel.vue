<template>
  <div class="workflow-panel" data-testid="receipt-panel">
    <p class="page-desc">
      每条刷新回执都回链原变更通知与已生效变更单，可核对实际刷新的实体与版本是否与通知依据一致。
    </p>
    <table class="data-table">
      <thead>
        <tr>
          <th>回执编号</th><th>通知编号</th><th>变更单号</th><th>实体/版本</th>
          <th>订阅方</th><th>回执状态</th><th>拒收原因</th><th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="receipt in rows" :key="receipt.id" :data-testid="`receipt-row-${receipt.id}`">
          <td>{{ receipt.回执编号 }}</td>
          <td>{{ receipt.通知编号 }}</td>
          <td>{{ receipt.变更单号 }}</td>
          <td>
            <span class="badge info">{{ receipt.实体编码 }} @ {{ receipt.生效版本 }}</span>
            <div v-if="receipt.刷新实体" class="page-desc">
              实际刷新：{{ receipt.刷新实体 }} @ {{ receipt.刷新版本 }}
            </div>
          </td>
          <td>{{ receipt.订阅方标识 }}</td>
          <td>
            <span class="badge" :class="receipt.回执状态 === '已刷新' ? 'ok' : 'bad'">
              {{ receipt.回执状态 }}
            </span>
          </td>
          <td>{{ receipt.拒收原因 || '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="emit('verify', receipt)">核对依据</button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td colspan="8" class="empty-state">暂无刷新回执</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup lang="ts">
import type { RefreshReceipt } from '@/api/workflow-service'

defineProps<{ rows: RefreshReceipt[] }>()

const emit = defineEmits<{
  (e: 'verify', receipt: RefreshReceipt): void
}>()
</script>
