<template>
  <div v-if="open" class="modal-backdrop" data-testid="workflow-modal" @click.self="close">
    <div class="modal modal-wide">
      <h3>{{ title }}</h3>

      <!-- 只读跟进详情 -->
      <dl v-if="mode === 'followup'" class="detail-list" data-testid="followup-detail">
        <template v-if="followup">
          <dt>通知编号</dt><dd>{{ followup.notice.通知编号 }}</dd>
          <dt>通知依据</dt><dd>{{ followup.notice.实体编码 }} @ {{ followup.notice.生效版本 }}</dd>
          <dt>原订阅方</dt><dd>{{ followup.notice.订阅方标识 }}</dd>
          <dt>当前订阅实体</dt><dd>{{ followup.current_subscription.join('、') || '—' }}</dd>
          <dt>订阅是否仍覆盖</dt>
          <dd>
            <span class="badge" :class="followup.subscription_still_covers ? 'ok' : 'bad'">
              {{ followup.subscription_still_covers ? '仍覆盖' : '已不覆盖（归属冲突）' }}
            </span>
          </dd>
          <dt>通知状态</dt><dd>{{ followup.notice.通知状态 }}</dd>
          <dt>办理结论</dt><dd>{{ followup.notice.处理结论 || '—' }}</dd>
          <dt>关联回执</dt>
          <dd v-if="followup.receipt">
            {{ followup.receipt.回执编号 }} · {{ followup.receipt.回执状态 }}
            <span v-if="followup.receipt.拒收原因">（{{ followup.receipt.拒收原因 }}）</span>
          </dd>
          <dd v-else>—</dd>
        </template>
      </dl>

      <!-- 改订订阅 -->
      <form v-else-if="mode === 'resubscribe'" @submit.prevent="submit">
        <label class="form-row">
          <span>新订阅实体（多个编码用逗号分隔，按编码片段精确匹配）</span>
          <input v-model="formText" data-testid="resubscribe-input" placeholder="例如：XCUS" required />
        </label>
      </form>

      <!-- 拒收原因 -->
      <form v-else-if="mode === 'reject'" @submit.prevent="submit">
        <p class="page-desc">
          通知依据：{{ targetNotice?.实体编码 }} @ {{ targetNotice?.生效版本 }}
        </p>
        <label class="form-row">
          <span>拒收原因（将写入刷新回执与订阅方拒收依据）</span>
          <textarea v-model="formText" data-testid="reject-reason" rows="3" required
            placeholder="例如：订阅已改订 XCUS，不再覆盖 CUS"></textarea>
        </label>
      </form>

      <!-- 接管订阅方 -->
      <form v-else-if="mode === 'handover'" @submit.prevent="submit">
        <p class="page-desc">
          通知依据：{{ targetNotice?.实体编码 }} @ {{ targetNotice?.生效版本 }}。
          接管方必须仍精确订阅该实体，否则会被拒绝。
        </p>
        <label class="form-row">
          <span>接管订阅方标识</span>
          <input v-model="formText" data-testid="handover-input" placeholder="例如：B" required />
        </label>
      </form>

      <!-- 关闭原因 -->
      <form v-else-if="mode === 'close'" @submit.prevent="submit">
        <p class="page-desc">仅当订阅方当前订阅不再覆盖通知实体时，才能以订阅变化为由关闭。</p>
        <label class="form-row">
          <span>关闭说明（可留空，系统自动生成订阅变化依据）</span>
          <textarea v-model="formText" data-testid="close-reason" rows="2"></textarea>
        </label>
      </form>

      <!-- 回执核对结果 -->
      <div v-else-if="mode === 'verify'" data-testid="verify-result">
        <dl class="detail-list">
          <template v-if="verifyResult">
            <dt>核对结论</dt>
            <dd>
              <span class="badge" :class="verifyResult.ok ? 'ok' : 'bad'">
                {{ verifyResult.ok ? '依据一致' : '依据不一致' }}
              </span>
            </dd>
            <dt>说明</dt><dd>{{ verifyResult.message }}</dd>
          </template>
        </dl>
      </div>

      <p v-if="errorMessage" class="error-text" data-testid="workflow-error">{{ errorMessage }}</p>

      <div class="page-actions">
        <button class="btn" type="button" @click="close">关闭</button>
        <button
          v-if="mode !== 'followup' && mode !== 'verify'"
          class="btn primary"
          type="button"
          data-testid="workflow-submit"
          :disabled="submitting"
          @click="submit"
        >
          {{ submitting ? '提交中…' : '确认' }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { ChangeNotice, FollowUp, RefreshReceipt } from '@/api/workflow-service'

export type WorkflowMode =
  | 'followup'
  | 'resubscribe'
  | 'reject'
  | 'handover'
  | 'close'
  | 'verify'

const props = defineProps<{
  open: boolean
  mode: WorkflowMode
  title: string
  targetNotice?: ChangeNotice | null
  followup?: FollowUp | null
  verifyResult?: { ok: boolean; message: string } | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'submit', text: string): void
}>()

const formText = ref('')
const submitting = ref(false)
const errorMessage = ref('')

function close() {
  errorMessage.value = ''
  formText.value = ''
  emit('close')
}

async function submit() {
  if (props.mode === 'resubscribe' && !formText.value.trim()) {
    errorMessage.value = '请填写改订后的订阅实体'
    return
  }
  if (props.mode === 'reject' && !formText.value.trim()) {
    errorMessage.value = '请填写拒收原因'
    return
  }
  if (props.mode === 'handover' && !formText.value.trim()) {
    errorMessage.value = '请填写接管订阅方标识'
    return
  }
  submitting.value = true
  try {
    emit('submit', formText.value.trim())
  } finally {
    submitting.value = false
  }
}

function resetForm(initial = '') {
  formText.value = initial
  errorMessage.value = ''
}

defineExpose({ resetForm, setError: (msg: string) => { errorMessage.value = msg } })
</script>
