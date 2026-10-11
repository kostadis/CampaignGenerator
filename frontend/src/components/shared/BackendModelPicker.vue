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
  /** Hide the help lines where the host page's own copy already explains the stored default. */
  showHelp?: boolean
}>(), { storedBackend: '', storedModel: '', modelLabel: 'Model', showHelp: true })

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
    <span v-if="showHelp" class="field-help">Blank uses <code>{{ configKey }}.backend</code>. The sidebar backend does not apply here. Not saved.</span>
  </label>
  <label class="field">
    <span class="field-label">{{ modelLabel }}</span>
    <input type="text" class="field-input" v-model="model" :placeholder="modelPlaceholder" spellcheck="false"
      :aria-label="modelLabel" />
    <span v-if="showHelp" class="field-help">Blank uses the stored model, or the chosen backend's default when it differs from the stored one.</span>
  </label>
</template>

<style scoped>
/* Scoped host styles never reach a child component, so the picker carries its own field styles.
   They default to the Summary-native page's; a host with a different field style (Threads) sets the
   --picker-* custom properties on a wrapper, and they inherit down. */
.field { display: block; margin-bottom: var(--picker-gap, 10px); min-width: 0; }
.field-label {
  display: block; margin-bottom: 3px;
  font-size: 11px; font-weight: 600; color: var(--text-sub);
}
.field-input {
  width: 100%; padding: 6px 8px; border-radius: 4px; box-sizing: border-box; outline: none;
  border: 1px solid var(--bg-surface1); background: var(--bg-base); color: var(--text);
  font-family: var(--picker-input-font, var(--mono)); font-size: var(--picker-input-size, 11px);
}
.field-input:focus { border-color: var(--mauve); }
.field-input::placeholder { color: var(--text-muted); }
.field-help { display: block; font-size: 10px; color: var(--text-muted); margin-top: 3px; }
.field-help code { font-family: var(--mono); font-size: 10px; }
</style>
