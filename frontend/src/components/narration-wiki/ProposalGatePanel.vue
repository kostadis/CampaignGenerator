<script setup lang="ts">
import { ref } from 'vue'

defineProps<{ activeProposalId: string | null; diff?: string; truncated?: boolean; disabled?: boolean }>()
const emit = defineEmits<{
  stage: [payload: { proposal_id: string; draft_relative: string; override_rationale: string | null }]
  apply: [proposalId: string]
  rule: [payload: { proposal_id: string; decision: 'accept' | 'reject' }]
}>()
const proposalId = ref('')
const draftRelative = ref('')
const overrideRationale = ref('')
</script>

<template>
  <section class="wiki-panel" aria-labelledby="proposal-heading">
    <h3 id="proposal-heading">Gate 2 — one atomic proposal</h3>
    <div class="wiki-resizable-panel proposal-scroll">
      <div class="proposal-form">
        <label>Proposal ID<input v-model="proposalId" type="text" /></label>
        <label>Draft path, relative to iteration<input v-model="draftRelative" type="text" /></label>
        <label>Stage-time GM override (optional)<textarea v-model="overrideRationale" rows="2" /></label>
        <button class="btn-primary" :disabled="disabled || !proposalId.trim() || !draftRelative.trim()"
          @click="emit('stage', { proposal_id: proposalId, draft_relative: draftRelative, override_rationale: overrideRationale.trim() || null })">
          Stage proposal
        </button>
      </div>
      <pre class="complete-diff">{{ diff || 'The complete non-wrapping staged diff will appear here.' }}</pre>
      <p v-if="truncated" class="diff-truncated">
        Diff truncated in transport. Read <code>proposals/{{ activeProposalId }}/change.diff</code> for the complete change before ruling.
      </p>
      <div v-if="activeProposalId" class="actions">
        <button class="btn-primary" :disabled="disabled" @click="emit('apply', activeProposalId)">Apply for comparison</button>
        <button class="btn-success" :disabled="disabled" @click="emit('rule', { proposal_id: activeProposalId, decision: 'accept' })">Accept change</button>
        <button class="btn-neutral" :disabled="disabled" @click="emit('rule', { proposal_id: activeProposalId, decision: 'reject' })">Reject and restore</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
h3 { font-size: 12px; margin-bottom: 8px; }
.proposal-form { min-width: 620px; }
label { display: block; color: var(--text-sub); font-size: 11px; margin-bottom: 8px; }
input, textarea { display: block; width: 100%; margin-top: 4px; padding: 6px 8px; border: 1px solid var(--bg-surface1); border-radius: 4px; background: var(--bg-base); color: var(--text); font: 11px var(--mono); }
.complete-diff { min-width: max-content; margin: 12px 0; padding: 10px; background: var(--bg-crust); color: var(--text-sub); font: 11px/1.45 var(--mono); white-space: pre; }
.diff-truncated { margin-bottom: 12px; color: var(--peach); font-size: 11px; }
.actions { display: flex; gap: 8px; min-width: 520px; }
</style>
