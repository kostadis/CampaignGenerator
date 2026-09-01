<script setup lang="ts">
import { ref, watch } from 'vue'

const props = defineProps<{ conflictId: string | null; disabled?: boolean }>()
const emit = defineEmits<{ rule: [payload: { conflict_id: string; resolution: string; rationale: string }] }>()
const resolution = ref('')
const rationale = ref('')

watch(() => props.conflictId, () => {
  resolution.value = ''
  rationale.value = ''
})

function submit() {
  if (!props.conflictId || !resolution.value.trim() || !rationale.value.trim()) return
  emit('rule', { conflict_id: props.conflictId, resolution: resolution.value, rationale: rationale.value })
}
</script>

<template>
  <section class="wiki-panel" aria-labelledby="conflict-heading">
    <h3 id="conflict-heading">Seed conflict ruling</h3>
    <div class="wiki-resizable-panel conflict-scroll">
      <p v-if="!conflictId" class="muted">No unresolved seed conflict.</p>
      <template v-else>
        <p>Reviewing one conflict: <code>{{ conflictId }}</code></p>
        <label>Resolution<textarea v-model="resolution" rows="3" /></label>
        <label>GM rationale<textarea v-model="rationale" rows="3" /></label>
        <button class="btn-success" :disabled="disabled || !resolution.trim() || !rationale.trim()" @click="submit">
          Persist conflict ruling
        </button>
      </template>
    </div>
  </section>
</template>

<style scoped>
h3 { font-size: 12px; margin-bottom: 8px; }
label { display: block; color: var(--text-sub); font-size: 11px; margin: 10px 0; }
textarea { display: block; width: 100%; min-width: 420px; margin-top: 4px; padding: 7px; border: 1px solid var(--bg-surface1); border-radius: 4px; background: var(--bg-base); color: var(--text); font: 11px var(--mono); }
code { font-family: var(--mono); color: var(--teal); }
.muted { color: var(--text-muted); }
</style>
