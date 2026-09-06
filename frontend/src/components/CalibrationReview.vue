<script setup lang="ts">
import { computed, ref } from 'vue'
const props = defineProps<{ calibration: any; busy: boolean; stale: boolean; selectedCount: number; command: (op: string, payload: any) => Promise<void> }>()
const emit = defineEmits<{ evidence: [value: any] }>()
const scene = ref(''); const speaker = ref(''); const risksOnly = ref(false)
const discussion = ref(''); const note = ref(''); const selected = ref<string[]>([])
const latest = computed(() => Object.fromEntries(props.calibration.decisions.map((d: any) => [d.finding_id, d])))
const cards = computed(() => props.calibration.cards)
const scenes = computed(() => [...new Set<string>(cards.value.map((c: any) => c.scene))])
const speakers = computed(() => [...new Set<string>(cards.value.map((c: any) => c.speaker))])
const rows = computed(() => cards.value.filter((c: any) => (!scene.value || c.scene === scene.value) && (!speaker.value || c.speaker === speaker.value) && (!risksOnly.value || c.risk)))
const categories = computed(() => [...new Set<string>(rows.value.map((c: any) => c.category))])
const tally = computed(() => {
  const counts: Record<string, number> = { approve: 0, reject: 0, discuss: 0, undecided: 0 }
  for (const c of cards.value) counts[latest.value[c.id]?.decision || 'undecided']!++
  return counts
})
const labels: Record<string, string> = { approve: 'Approved', reject: 'Rejected — keep original', discuss: 'Discuss', undecided: 'Not reviewed' }
async function decide(decision: string, ids: string[], rationale = '') {
  await props.command('calibration-decide', { decisions: ids.map(id => ({ finding_id: id, finding_sha256: cards.value.find((c: any) => c.id === id).finding_sha256, decision, ...(rationale.trim() ? { rationale: rationale.trim() } : {}) })) })
}
async function discuss(id: string) {
  discussion.value = id
  note.value = latest.value[id]?.decision === 'discuss' ? latest.value[id].rationale : ''
  await decide('discuss', [id], note.value)
}
</script>

<template>
  <section aria-label="Voice smoothing calibration" class="calibration">
    <h4>{{ calibration.report.title }}</h4>
    <p>Review the smoothing approach before the agent renders the remaining scenes. {{ scenes.length }} of {{ selectedCount }} selected scenes are represented here. This sample is derived dialogue; the source stays unchanged.</p>
    <p>{{ calibration.report.method }}</p>
    <p>Approve accepts the displayed example. Reject keeps its original wording. Discuss leaves a question for the agent. Neither a card decision nor calibration approval signs off the completed draft.</p>
    <div class="tally" role="status" aria-label="Calibration progress">
      {{ tally.approve }} approved · {{ tally.reject }} rejected · {{ tally.discuss }} discuss · {{ tally.undecided }} not reviewed
    </div>
    <div class="controls">
      <label>Calibration scene <select v-model="scene"><option value="">All scenes</option><option v-for="s in scenes" :key="s">{{ s }}</option></select></label>
      <label>Speaker <select v-model="speaker"><option value="">All speakers</option><option v-for="s in speakers" :key="s">{{ s }}</option></select></label>
      <label><input v-model="risksOnly" type="checkbox" /> Only flagged examples</label>
    </div>
    <details><summary>Voice and genre authorities</summary><button v-for="e in calibration.report.authorities" :key="e.path" @click="emit('evidence', e)">Read {{ e.path }}</button></details>
    <details class="bulk"><summary>Bulk decisions · {{ selected.length }} selected</summary>
      <button :disabled="busy || stale" @click="selected = rows.map((c: any) => c.id)">Select displayed examples</button>
      <button @click="selected = []">Clear selection</button>
      <button :disabled="busy || stale || !selected.length" @click="decide('approve', selected)">Approve selected examples</button>
      <button :disabled="busy || stale || !selected.length" @click="decide('reject', selected)">Reject selected examples</button>
      <button :disabled="busy || stale || !selected.length" @click="decide('discuss', selected)">Discuss selected examples</button>
    </details>
    <section v-for="category in categories" :key="category" :aria-label="category">
      <h4>{{ category }}</h4>
      <article v-for="card in rows.filter((c: any) => c.category === category)" :key="card.id" :aria-label="`Calibration ${card.id}`">
        <header><h5>{{ card.speaker }} · Scene {{ card.scene }} · {{ card.location }}</h5><strong>{{ labels[latest[card.id]?.decision || 'undecided'] }}</strong></header>
        <p>{{ card.rationale }}</p><p v-if="card.risk" class="risk">Needs attention: {{ card.risk }}</p>
        <div class="comparison"><div><h5>Original wording</h5><blockquote>{{ card.before }}</blockquote></div><div><h5>Smoothed proposal</h5><blockquote>{{ card.after }}</blockquote></div></div>
        <div class="verdicts">
          <button :disabled="busy || stale" :aria-pressed="latest[card.id]?.decision === 'approve'" @click="decide('approve', [card.id])">Approve</button>
          <button :disabled="busy || stale" :aria-pressed="latest[card.id]?.decision === 'reject'" @click="decide('reject', [card.id])">Reject</button>
          <button :disabled="busy || stale" :aria-pressed="latest[card.id]?.decision === 'discuss'" @click="discuss(card.id)">Discuss</button>
        </div>
        <div v-if="discussion === card.id">
          <label :for="`calibration-note-${card.id}`">Optional question or intended wording for the agent</label>
          <textarea :id="`calibration-note-${card.id}`" v-model="note" rows="3" />
          <button :disabled="busy || stale" @click="decide('discuss', [card.id], note)">Save note</button><button @click="discussion = ''">Close</button>
        </div>
        <p v-if="latest[card.id]">Saved {{ labels[latest[card.id].decision] }}: {{ latest[card.id].rationale }}</p>
        <details><summary>Evidence and source hashes</summary><code>{{ card.source.path }} · {{ card.source.sha256 }}</code><br /><code>{{ card.sample.path }} · {{ card.sample.sha256 }}</code>
          <div class="controls"><button @click="emit('evidence', card.source)">Read original scene</button><button @click="emit('evidence', card.sample)">Read calibration sample</button></div>
        </details>
        <label><input v-model="selected" type="checkbox" :value="card.id" :disabled="busy || stale" /> Select example for bulk decisions</label>
      </article>
    </section>
    <div class="gate">
      <h4>Calibration handoff</h4>
      <p v-if="calibration.approved">Calibration saved. Copy the handoff below and ask the agent to continue the remaining selected scenes. The completed draft still requires checks and your separate sign-off.</p>
      <p v-else>Resolve each example, then confirm the approach. Rejected examples retain their original wording; discussion must be resolved with the agent.</p>
      <button :disabled="busy || stale || calibration.approved || !!calibration.unresolved.length" @click="command('calibration-approve', { calibration_binding: calibration.binding })">Use this calibration</button>
    </div>
  </section>
</template>

<style scoped>
.calibration { margin: 1rem 0; min-width: 0; } article, .gate, .bulk { border: 1px solid #8886; border-radius: .4rem; padding: 1rem; margin: 1rem 0; }
header, .controls, .verdicts { display: flex; flex-wrap: wrap; gap: .75rem; justify-content: space-between; }
h4, h5 { margin: .5rem 0; font-size: 1rem; } .comparison { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; }
blockquote { margin: .5rem 0 1rem; padding: .6rem; border-left: 3px solid #8886; white-space: pre-wrap; }
.tally { position: sticky; top: 3.5rem; z-index: 2; background: var(--bg-primary, #20232a); color: var(--text-primary, #fff); padding: .8rem; border: 1px solid #8886; border-radius: .4rem; }
button { color: inherit; background: var(--panel-bg, #303044); border: 1px solid #8888; border-radius: .3rem; font: inherit; cursor: pointer; padding: .5rem; overflow-wrap: anywhere; max-width: 100%; } button:disabled { cursor: not-allowed; opacity: .5; } button[aria-pressed=true] { outline: 2px solid currentColor; }
.verdicts button { flex: 1; } textarea { width: 100%; box-sizing: border-box; } code { overflow-wrap: anywhere; } .risk { border-left: 3px solid #d59638; padding-left: .7rem; }
@media (max-width: 800px) { .comparison { grid-template-columns: 1fr; } }
</style>
