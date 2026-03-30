<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { apiFetch } from '../../api/client'
import { resolvePathWithBase, type ResolveBase } from '../../utils/paths'

const props = defineProps<{
  modelValue: string
  label: string
  help?: string
  required?: boolean
  isOutput?: boolean
  placeholder?: string
  /** If true, don't resolve relative paths (use for session_dir itself). */
  absolute?: boolean
  /** Which base directory to resolve relative paths against. Default: 'session'. */
  resolveBase?: ResolveBase
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
}>()

const exists = ref<boolean | null>(null)
let checkTimer: ReturnType<typeof setTimeout> | null = null

const resolvedPath = computed(() => {
  if (props.absolute) return props.modelValue.trim()
  return resolvePathWithBase(props.modelValue, props.resolveBase || 'session')
})

async function checkPath(path: string) {
  if (!path.trim() || props.isOutput) {
    exists.value = null
    return
  }
  try {
    const data = await apiFetch(`/api/config/path-status?path=${encodeURIComponent(path)}`)
    exists.value = data.exists
  } catch {
    exists.value = null
  }
}

// Check the resolved path (not the raw value)
watch(resolvedPath, (val) => {
  if (checkTimer) clearTimeout(checkTimer)
  checkTimer = setTimeout(() => checkPath(val), 300)
}, { immediate: true })

const isRelative = computed(() => {
  const raw = props.modelValue.trim()
  if (!raw || raw.startsWith('/') || raw.startsWith('~')) return false
  return resolvedPath.value !== raw
})

function onInput(e: Event) {
  emit('update:modelValue', (e.target as HTMLInputElement).value)
}
</script>

<template>
  <div class="path-field">
    <label class="field-label">
      {{ label }}
      <span v-if="required" class="required">*</span>
      <span v-if="exists === true" class="status ok">&#x2705;</span>
      <span v-else-if="exists === false && modelValue.trim()" class="status missing">&#x274C; not found</span>
    </label>
    <input
      type="text"
      class="field-input"
      :value="modelValue"
      @input="onInput"
      :placeholder="placeholder || ''"
    />
    <div v-if="isRelative" class="resolved-hint">&rarr; {{ resolvedPath }}</div>
    <div v-if="help" class="field-help">{{ help }}</div>
  </div>
</template>

<style scoped>
.path-field { margin-bottom: 10px; }

.field-label {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: var(--text-sub);
  margin-bottom: 3px;
}
.required { color: var(--red); }
.status { font-size: 10px; margin-left: 4px; }
.status.ok { color: var(--green); }
.status.missing { color: var(--red); font-size: 9px; }

.field-input {
  width: 100%;
  padding: 6px 8px;
  border-radius: 4px;
  border: 1px solid var(--bg-surface1);
  background: var(--bg-base);
  color: var(--text);
  font-family: var(--mono);
  font-size: 11px;
  outline: none;
  transition: border-color .1s;
}
.field-input:focus { border-color: var(--mauve); }

.resolved-hint {
  font-size: 9px;
  color: var(--text-muted);
  font-family: var(--mono);
  margin-top: 2px;
  opacity: 0.7;
}

.field-help {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 2px;
  line-height: 1.4;
}
</style>
