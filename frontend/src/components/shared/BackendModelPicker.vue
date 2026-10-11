<script setup lang="ts">
// Per-run backend + model for a step whose selection is stored in a config block
// (e.g. grounding.yaml summary_native.extract). Neither value is saved: blank means
// the stored one. The sidebar backend never applies to these steps, so this is the
// only way to run one on another backend without editing the config.
//
// The server drops the stored model when the chosen backend differs from the stored
// one (the model belongs to its backend), so a blank model then means "that
// backend's default" — the placeholder says which.
import { computed } from 'vue'

const BACKENDS = ['anthropic', 'dgx', 'openrouter', 'claude-code', 'codex-cli'] as const

const backend = defineModel<string>('backend', { default: '' })
const model = defineModel<string>('model', { default: '' })

const props = withDefaults(defineProps<{
  /** The config block the stored values come from, shown in the help text. */
  configKey: string
  storedBackend?: string
  storedModel?: string
  modelLabel?: string
}>(), { storedBackend: '', storedModel: '', modelLabel: 'Model' })

const modelPlaceholder = computed(() =>
  backend.value && backend.value !== props.storedBackend
    ? `${backend.value} default`
    : (props.storedModel || 'stored default'))
</script>

<template>
  <label class="field">
    <span class="field-label">Backend</span>
    <select class="field-input" v-model="backend" aria-label="Backend">
      <option value="">stored{{ storedBackend ? ` (${storedBackend})` : '' }}</option>
      <option v-for="b in BACKENDS" :key="b" :value="b">{{ b }}</option>
    </select>
    <span class="field-help">Blank uses <code>{{ configKey }}.backend</code>. The sidebar backend does not apply here. Not saved.</span>
  </label>
  <label class="field">
    <span class="field-label">{{ modelLabel }}</span>
    <input type="text" class="field-input" v-model="model" :placeholder="modelPlaceholder" spellcheck="false"
      :aria-label="modelLabel" />
    <span class="field-help">Blank uses the stored model, or the chosen backend's default when it differs from the stored one.</span>
  </label>
</template>
