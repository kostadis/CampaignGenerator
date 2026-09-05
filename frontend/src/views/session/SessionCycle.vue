<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiPost } from '../../api/client'
import { useConfigStore } from '../../stores/config'

const route = useRoute()
const router = useRouter()
const configStore = useConfigStore()
const session = ref(String(route.query.session || ''))
const config = ref('')
const workspace = ref<any>(null)
const selectedRun = ref(String(route.query.run || ''))
const actor = ref('')
const rationale = ref('')
const group = ref('')
const scene = ref('')
const chosen = ref<string[]>([])
const exported = ref<any>(null)
const preview = ref('')
const error = ref('')
const busy = ref(false)
const operation = ref('start')
const payload = ref('{}')
const chapters = ref('')
const notes = ref('')
const result = ref('')
const run = computed(() => workspace.value?.state.runs.find((r: any) => r.id === selectedRun.value))
const view = computed(() => workspace.value?.runs.find((r: any) => r.id === selectedRun.value))
const rows = computed(() => (exported.value?.findings || []).filter((f: any) => !scene.value || f.scene === scene.value))
const scenes = computed(() => [...new Set<string>((exported.value?.findings || []).map((f: any) => f.scene).filter(Boolean))])
const operations = ['import-legacy', 'memory-scope', 'memory-plan', 'memory-events', 'promotion-scope', 'promote', 'catalog', 'execute', 'resume', 'migrate', 'start', 'submit', 'check', 'decide', 'approve', 'apply', 'select-version', 'export', 'import', 'recover', 'evidence']

async function invoke(op: string, data: any = {}) {
  const body = {
    operation: op, session_dir: session.value, config: config.value || null,
    expected_revision: workspace.value?.state.revision ?? null, payload: data,
  }
  if (op !== 'execute') return await apiPost('/api/session-workflow/command', body)
  const response = await fetch('/api/session-workflow/command', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!response.ok || !response.body) throw Error(await response.text())
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = ''; let output = ''; let done: any = null
  while (true) {
    const chunk = await reader.read(); if (chunk.done) break
    buffer += decoder.decode(chunk.value, { stream: true })
    const frames = buffer.split('\n\n'); buffer = frames.pop() || ''
    for (const frame of frames) {
      const value = frame.split('\n').find(line => line.startsWith('data: '))?.slice(6)
      if (!value) continue
      const parsed = JSON.parse(value)
      if (frame.includes('event: done')) done = parsed
      else if (typeof parsed === 'string') { output += parsed; result.value = output }
    }
  }
  if (!done || done.returncode !== 0) throw Error(done?.error || output || 'Execution interrupted; inspect resume status.')
  return { output, done }
}
async function refresh() {
  workspace.value = await invoke('status')
  chapters.value = workspace.value.state.chapters_selected.join('\n')
  notes.value = workspace.value.state.notes_selected.join('\n')
  await router.replace({ query: { ...route.query, session: session.value, run: selectedRun.value || undefined } })
  if (selectedRun.value) exported.value = await invoke('export', { run_id: selectedRun.value })
}
async function guarded(action: () => Promise<void>) {
  busy.value = true; error.value = ''
  try { await action() } catch (e) { error.value = String(e) } finally { busy.value = false }
}
async function chooseRun(id: string) {
  selectedRun.value = id; chosen.value = []; preview.value = ''; scene.value = ''
  await guarded(refresh)
}
async function decide(decision: string) {
  await guarded(async () => {
    if (!chosen.value.length || !actor.value.trim() || !rationale.value.trim()) throw Error('Select findings and enter your name and rationale.')
    await invoke('decide', { run_id: run.value.id, decisions: chosen.value.map(id => ({
      finding_id: id, finding_sha256: exported.value.findings.find((f: any) => f.id === id).finding_sha256,
      decision, actor: actor.value, rationale: rationale.value, group: group.value || null, at: new Date().toISOString(),
    })) })
    await refresh()
  })
}
async function approve() {
  await guarded(async () => {
    await invoke('approve', { run_id: run.value.id, actor: actor.value, rationale: rationale.value, draft_binding: view.value.approval_binding })
    await refresh()
  })
}
async function apply() {
  await guarded(async () => { await invoke('apply', { run_id: run.value.id, finding_ids: chosen.value }); await refresh() })
}
async function showEvidence(evidence: any) {
  await guarded(async () => { preview.value = (await invoke('evidence', evidence)).text })
}
async function downloadReview() {
  await guarded(async () => {
    const data = await invoke('export', { run_id: run.value.id })
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = `review-${run.value.id}.json`; link.click(); URL.revokeObjectURL(url)
  })
}
async function importReview(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (file) await guarded(async () => { await invoke('import', { document: JSON.parse(await file.text()) }); await refresh() })
}
async function execute() {
  await guarded(async () => { result.value = JSON.stringify(await invoke(operation.value, JSON.parse(payload.value)), null, 2); await refresh() })
}
onMounted(async () => {
  if (!session.value) session.value = configStore.resolved.runtime?.session_dir || ''
  if (session.value) await guarded(refresh)
})
</script>

<template>
  <main class="cycle">
    <h2>Session production and review</h2>
    <p>Review progress is saved beside the session artifacts and shared with CLI and chat.</p>
    <div class="controls">
      <label>Session directory <input v-model="session" /></label>
      <label>Campaign config (initialization) <input v-model="config" /></label>
      <button :disabled="busy || !session" @click="guarded(refresh)">Load / refresh</button>
      <button :disabled="busy || !session" @click="guarded(async () => { workspace = await invoke('init'); await refresh() })">Initialize record</button>
    </div>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="workspace?.recovery_required" role="alert">An interrupted application needs recovery. Originals are preserved.</p>
    <div v-if="workspace" class="workspace">
      <nav aria-label="Production stages">
        <p>Revision {{ workspace.state.revision }}</p>
        <button v-for="r in workspace.runs" :key="r.id" :disabled="busy" @click="chooseRun(r.id)">
          {{ r.stage }} · {{ r.status }} <small>{{ r.id.slice(0, 8) }}</small>
        </button>
      </nav>
      <section v-if="run">
        <h3>{{ run.stage }} · {{ view.status }}</h3>
        <p>{{ run.generation.backend }} / {{ run.generation.model || 'backend default' }} / {{ run.generation.effort || 'default effort' }}</p>
        <p>Checks needed: {{ view.missing_checks.join(', ') || 'none' }}. Unresolved: {{ view.unresolved_findings.length }}.</p>
        <p v-for="reason in view.stale_reasons" :key="reason" class="error">{{ reason }}</p>
        <details><summary>Resolved task, inputs, selection and generation metadata</summary><pre>{{ JSON.stringify(run, null, 2) }}</pre></details>
        <div class="controls">
          <button v-for="e in run.outputs" :key="e.path" @click="showEvidence(e)">Read {{ e.path }} ({{ e.label }})</button>
          <button @click="downloadReview">Export review JSON</button>
          <label>Import reviewed JSON <input type="file" accept="application/json" @change="importReview" /></label>
        </div>
        <label>Scene <select v-model="scene"><option value="">All scenes</option><option v-for="s in scenes" :key="s">{{ s }}</option></select></label>
        <button @click="chosen = rows.map((f: any) => f.id)">Select displayed findings</button>
        <button @click="chosen = []">Clear selection</button>
        <article v-for="f in rows" :key="f.id">
          <label><input v-model="chosen" type="checkbox" :value="f.id" /> {{ f.id }} · {{ f.scene }} · {{ f.location }}</label>
          <p>{{ f.description }}</p><p>Proposed action: {{ f.proposed_action }}</p>
          <p v-if="f.rule">Rule: {{ f.rule.reference }} · {{ f.rule.scope }} · {{ f.rule.authority.path }}</p>
          <p v-for="(meaning, decision) in f.consequences" :key="decision">{{ decision }}: {{ meaning }}</p>
          <pre v-if="f.change">{{ f.change.before }} → {{ f.change.after }}</pre>
          <button @click="showEvidence(f.evidence)">Read evidence</button>
          <p>Decision: {{ [...run.decisions].reverse().find((d: any) => d.finding_id === f.id)?.decision || 'unresolved' }}</p>
        </article>
        <div class="controls">
          <label>Your name <input v-model="actor" /></label>
          <label>Rationale <input v-model="rationale" /></label>
          <label>Discussion group (optional) <input v-model="group" /></label>
          <button :disabled="busy || !chosen.length" @click="decide('approve')">Approve selected findings</button>
          <button :disabled="busy || !chosen.length" @click="decide('reject')">Reject selected findings</button>
          <button :disabled="busy || !chosen.length" @click="decide('discuss')">Discuss selected findings</button>
          <button :disabled="busy || !chosen.length" @click="apply">Apply selected approved changes</button>
        </div>
        <button :disabled="busy" @click="guarded(async () => { result = JSON.stringify(await invoke('execute', { run_id: run.id }), null, 2); await refresh() })">Execute / show native task</button>
        <button :disabled="busy" @click="guarded(async () => { result = JSON.stringify(await invoke('resume'), null, 2); await refresh() })">Resume status</button>
        <p>A completed check does not approve a draft. Read every output before signing off.</p>
        <button :disabled="busy || !actor.trim() || !rationale.trim()" @click="approve">I have reviewed this draft — approve</button>
        <button :disabled="busy" @click="guarded(async () => { await invoke('select-version', { run_id: run.id }); await refresh() })">Select approved version for downstream work</button>
      </section>
    </div>
    <details v-if="workspace">
      <summary>Memory and next-session prep scope</summary>
      <label>Selected chapter paths (one per line, campaign-relative)<textarea v-model="chapters" rows="4" /></label>
      <label>Selected note paths (one per line; blank selects no notes)<textarea v-model="notes" rows="4" /></label>
      <button :disabled="busy || !chapters.trim()" @click="guarded(async () => { await invoke('memory-scope', { chapters: chapters.split('\n').map(x => x.trim()).filter(Boolean), notes: notes.split('\n').map(x => x.trim()).filter(Boolean) }); await refresh() })">Save explicit scope</button>
      <button :disabled="busy" @click="guarded(async () => { result = JSON.stringify(await invoke('memory-plan'), null, 2) })">Inspect lineage, freshness and event prerequisites</button>
    </details>
    <pre v-if="preview" class="preview">{{ preview }}</pre>
    <details>
      <summary>CLI / agent interchange commands</summary>
      <p>Use the same JSON request documented in the operator guide. All results and refusals appear below.</p>
      <label>Operation <select v-model="operation"><option v-for="op in operations" :key="op">{{ op }}</option></select></label>
      <label>JSON request <textarea v-model="payload" rows="12" /></label>
      <button :disabled="busy" @click="execute">Run command</button>
      <pre>{{ result }}</pre>
    </details>
  </main>
</template>

<style scoped>
.cycle { padding: 1.5rem; } .controls { display: flex; gap: .8rem; flex-wrap: wrap; align-items: end; margin: 1rem 0; }
label { display: block; } input:not([type=checkbox]), select, textarea { display: block; padding: .4rem; }
.workspace { display: grid; grid-template-columns: 15rem minmax(0, 1fr); gap: 1.5rem; }
nav button { display: block; width: 100%; text-align: left; padding: .6rem; margin-bottom: .4rem; }
article { border: 1px solid #8886; padding: 1rem; margin: .8rem 0; } .error { color: #cf4d4d; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 35rem; overflow: auto; } textarea { width: 100%; }
button { cursor: pointer; } button:disabled { cursor: wait; opacity: .5; }
@media (max-width: 800px) { .workspace { grid-template-columns: 1fr; } }
</style>
