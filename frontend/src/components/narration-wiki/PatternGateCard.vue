<script setup lang="ts">
import { ref } from 'vue'

defineProps<{ disabled?: boolean }>()
const emit = defineEmits<{
  rule: [payload: {
    pattern_slug: string
    decision: 'accept' | 'reject'
    tier: 'campaign' | 'portable' | null
    named_portable_override: boolean
    rationale: string | null
  }]
}>()
const patternSlug = ref('')
const tier = ref<'campaign' | 'portable'>('campaign')
const namedOverride = ref(false)
const rationale = ref('')

function rule(decision: 'accept' | 'reject') {
  if (!patternSlug.value.trim()) return
  emit('rule', {
    pattern_slug: patternSlug.value,
    decision,
    tier: decision === 'accept' ? tier.value : null,
    named_portable_override: decision === 'accept' && tier.value === 'portable' && namedOverride.value,
    rationale: rationale.value.trim() || null,
  })
}
</script>

<template>
  <section class="wiki-panel" aria-labelledby="pattern-heading">
    <h3 id="pattern-heading">Gate 1 — one durable pattern</h3>
    <div class="wiki-resizable-panel pattern-scroll">
      <label>Pattern slug<input v-model="patternSlug" type="text" autocomplete="off" /></label>
      <div class="section-grid" aria-label="Required pattern sections">
        <span>Problem</span><span>Root Cause</span><span>Corrective Strategy</span><span>Evidence</span>
      </div>
      <label>Tier
        <select v-model="tier"><option value="campaign">Campaign</option><option value="portable">Portable</option></select>
      </label>
      <label v-if="tier === 'portable'" class="check">
        <input v-model="namedOverride" type="checkbox"> I explicitly approve named/campaign content for portable placement
      </label>
      <label v-if="tier === 'portable'">Override rationale<textarea v-model="rationale" rows="2" /></label>
      <div class="actions">
        <button class="btn-success" :disabled="disabled || !patternSlug.trim()" @click="rule('accept')">Accept pattern</button>
        <button class="btn-neutral" :disabled="disabled || !patternSlug.trim()" @click="rule('reject')">Reject pattern</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
h3 { font-size: 12px; margin-bottom: 8px; }
label { display: block; color: var(--text-sub); font-size: 11px; margin-bottom: 9px; }
input[type="text"], textarea, select { margin-top: 4px; padding: 6px 8px; border: 1px solid var(--bg-surface1); border-radius: 4px; background: var(--bg-base); color: var(--text); font: 11px var(--mono); }
input[type="text"], textarea { display: block; width: 100%; min-width: 420px; }
.check { display: flex; gap: 6px; align-items: center; min-width: 540px; }
.section-grid { display: grid; grid-template-columns: repeat(4, minmax(150px, 1fr)); gap: 6px; min-width: 680px; margin: 8px 0; }
.section-grid span { padding: 8px; background: var(--bg-surface0); border-radius: 4px; color: var(--text-sub); font-size: 10px; }
.actions { display: flex; gap: 8px; }
</style>
