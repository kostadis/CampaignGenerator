<script setup lang="ts">
import { ref, computed } from 'vue'
import { connectSSE } from '../../api/sse'
import { useConfigStore } from '../../stores/config'
import StreamOutput from './StreamOutput.vue'

const props = defineProps<{
  /** SSE endpoint URL (e.g. '/api/workflow/run/vtt-summary') */
  endpoint: string
  /** Query parameters to send */
  params: Record<string, any>
  /** Disable the run button */
  disabled?: boolean
  /** Label for the run button */
  label?: string
}>()

const emit = defineEmits<{
  done: [returncode: number]
}>()

const config = useConfigStore()
const output = ref('')
const status = ref<'idle' | 'running' | 'done' | 'error'>('idle')
const returnCode = ref<number | null>(null)

const buttonLabel = computed(() => {
  if (status.value === 'running') return 'Running\u2026'
  return props.label || '\u25B6 Run'
})

/** Build the command preview string */
const commandPreview = computed(() => {
  const parts: string[] = []
  const p = props.params
  // Just show the endpoint and key params for preview
  for (const [k, v] of Object.entries(p)) {
    if (v === '' || v === false || v === null || v === undefined) continue
    if (Array.isArray(v)) {
      for (const item of v) {
        if (item) parts.push(`--${k} ${item}`)
      }
    } else if (typeof v === 'boolean') {
      parts.push(`--${k}`)
    } else {
      parts.push(`--${k} ${v}`)
    }
  }
  return parts.join(' \\\n  ')
})

function run() {
  if (status.value === 'running' || props.disabled) return
  if (!config.apiKeyPresent) return

  status.value = 'running'
  output.value = ''
  returnCode.value = null

  // Build query string from params
  const url = new URL(props.endpoint, window.location.origin)
  for (const [k, v] of Object.entries(props.params)) {
    if (v === '' || v === false || v === null || v === undefined) continue
    if (Array.isArray(v)) {
      for (const item of v) {
        if (item) url.searchParams.append(k, item)
      }
    } else if (typeof v === 'boolean') {
      url.searchParams.set(k, 'true')
    } else {
      url.searchParams.set(k, String(v))
    }
  }

  connectSSE(url.pathname + url.search, {
    onData(text) {
      output.value += text
    },
    onDone(rc) {
      status.value = rc === 0 ? 'done' : 'error'
      returnCode.value = rc
      emit('done', rc)
    },
    onError() {
      status.value = 'error'
    },
  })
}

function clear() {
  output.value = ''
  status.value = 'idle'
  returnCode.value = null
}
</script>

<template>
  <div class="run-panel">
    <!-- Command preview -->
    <div v-if="commandPreview" class="cmd-preview">
      <pre>{{ commandPreview }}</pre>
    </div>

    <!-- Controls -->
    <div class="run-controls">
      <button
        class="btn-success"
        :disabled="disabled || status === 'running' || !config.apiKeyPresent"
        @click="run"
      >{{ buttonLabel }}</button>

      <span v-if="!config.apiKeyPresent" class="warning">
        ANTHROPIC_API_KEY not set
      </span>

      <span v-if="returnCode !== null" class="rc" :class="returnCode === 0 ? 'rc-ok' : 'rc-err'">
        {{ returnCode === 0 ? 'Success' : `Exit code: ${returnCode}` }}
      </span>

      <span style="flex:1"></span>
      <button v-if="output" class="btn-neutral btn-sm" @click="clear">Clear</button>
    </div>

    <!-- Streaming output -->
    <div v-if="output" class="output-container">
      <StreamOutput :text="output" />
    </div>
  </div>
</template>

<style scoped>
.run-panel {
  border-top: 1px solid var(--bg-surface0);
  display: flex;
  flex-direction: column;
}

.cmd-preview {
  background: #141420;
  border-bottom: 1px solid var(--bg-surface0);
  padding: 8px 12px;
  max-height: 80px;
  overflow-y: auto;
}
.cmd-preview pre {
  font-family: var(--mono);
  font-size: 10px;
  line-height: 1.5;
  color: var(--text-muted);
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}

.run-controls {
  padding: 8px 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--bg-mantle);
  border-bottom: 1px solid var(--bg-surface0);
}

.warning { font-size: 11px; color: var(--peach); font-weight: 600; }
.rc { font-size: 11px; font-weight: 600; }
.rc-ok { color: var(--green); }
.rc-err { color: var(--red); }

.output-container {
  flex: 1;
  min-height: 150px;
  max-height: 400px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
</style>
