<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { apiFetch } from '../../api/client'
import { resolvePathWithBase, type ResolveBase } from '../../utils/paths'

const props = defineProps<{
  modelValue: string
  label: string
  help?: string
  required?: boolean
  /** Which base directory to resolve relative paths against. Default: 'session'. */
  resolveBase?: ResolveBase
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const pathStatuses = ref<Record<string, boolean>>({})
let checkTimer: ReturnType<typeof setTimeout> | null = null

const paths = computed(() =>
  props.modelValue.split('\n').map(l => l.trim()).filter(Boolean)
)

function resolve(raw: string): string {
  return resolvePathWithBase(raw, props.resolveBase || 'session')
}

async function checkPaths() {
  const results: Record<string, boolean> = {}
  for (const p of paths.value) {
    const resolved = resolve(p)
    try {
      const data = await apiFetch(`/api/config/path-status?path=${encodeURIComponent(resolved)}`)
      results[p] = data.exists
    } catch {
      results[p] = false
    }
  }
  pathStatuses.value = results
}

watch(paths, () => {
  if (checkTimer) clearTimeout(checkTimer)
  checkTimer = setTimeout(checkPaths, 500)
}, { immediate: true })

function onInput(e: Event) {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
}
</script>

<template>
  <div class="multi-path-field">
    <label class="field-label">
      {{ label }}
      <span v-if="required" class="required">*</span>
    </label>
    <textarea
      class="field-textarea"
      :value="modelValue"
      @input="onInput"
      rows="3"
      placeholder="One path per line"
      spellcheck="false"
    />
    <div v-if="paths.length > 0" class="path-statuses">
      <span v-for="p in paths" :key="p" class="path-status">
        <span :class="pathStatuses[p] === true ? 'ok' : pathStatuses[p] === false ? 'missing' : 'checking'">
          {{ pathStatuses[p] === true ? '\u2705' : pathStatuses[p] === false ? '\u274C' : '\u23F3' }}
        </span>
        <span class="path-name">{{ p.split('/').pop() }}</span>
      </span>
    </div>
    <div v-if="help" class="field-help">{{ help }}</div>
  </div>
</template>

<style scoped>
.multi-path-field { margin-bottom: 10px; }

.field-label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-sub);
  margin-bottom: 3px;
}
.required { color: var(--red); }

.field-textarea {
  width: 100%;
  padding: 6px 8px;
  border-radius: 4px;
  border: 1px solid var(--bg-surface1);
  background: var(--bg-base);
  color: var(--text);
  font-family: var(--mono);
  font-size: 11px;
  outline: none;
  resize: vertical;
  line-height: 1.6;
  transition: border-color .1s;
}
.field-textarea:focus { border-color: var(--mauve); }

.path-statuses {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 3px;
}
.path-status {
  font-size: 10px;
  display: flex;
  align-items: center;
  gap: 2px;
}
.path-name { color: var(--text-muted); }
.ok { color: var(--green); }
.missing { color: var(--red); }
.checking { color: var(--text-muted); }

.field-help {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 2px;
  line-height: 1.4;
}
</style>
