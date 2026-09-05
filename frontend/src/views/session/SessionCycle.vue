<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
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
const notice = ref('')
const discussion = ref('')
const discussionNote = ref('')
const handoffOpen = ref(false)
const savedDecisions = computed(() => Object.fromEntries((run.value?.decisions || []).map((d: any) => [d.finding_id, d])))
const decisionLabels: Record<string, string> = { approve: 'Approved', reject: 'Rejected', discuss: 'Discuss' }
const decisionLabel = (value?: string) => decisionLabels[value || ''] || 'Not reviewed'
const handoff = computed(() => {
  const items = (exported.value?.findings || []).map((f: any) => {
    const d = savedDecisions.value[f.id]
    return d ? `${f.id}: ${d.decision} — ${d.rationale}` : `${f.id}: not reviewed`
  })
  return `Continue the session review using the saved workflow state.\nCampaign configuration: ${workspace.value?.state.config}\nSession directory: ${session.value}\nRun: ${selectedRun.value} (${run.value?.stage})\nRead the current findings, source hashes, and saved decisions from disk. Discuss the unresolved items with me; do not infer rulings for unreviewed findings. Apply only explicitly approved replacements and prepare the resulting draft for review. Stop before draft sign-off or the next production stage.\n\nSaved review at revision ${workspace.value?.state.revision}:\n${items.join('\n')}`
})
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
  busy.value = true; error.value = ''; notice.value = ''
  try { await action() } catch (e) { error.value = String(e) } finally { busy.value = false }
}
async function chooseRun(id: string) {
  selectedRun.value = id; chosen.value = []; preview.value = ''; scene.value = ''; discussion.value = ''; handoffOpen.value = false
  await guarded(refresh)
}
async function decide(decision: string, ids: string[] = chosen.value, note?: string) {
  await guarded(async () => {
    if (!ids.length) throw Error('Select findings before saving a decision.')
    const reason = note === undefined ? rationale.value.trim() : note.trim()
    await invoke('decide', { run_id: run.value.id, decisions: ids.map(id => ({
      finding_id: id, finding_sha256: exported.value.findings.find((f: any) => f.id === id).finding_sha256,
      decision, ...(reason ? { rationale: reason } : {}),
      group: ids.length > 1 ? group.value || null : null, at: new Date().toISOString(),
    })) })
    await refresh()
    discussion.value = ''
    notice.value = `${decisionLabel(decision)} saved for ${ids.length === 1 ? ids[0] : `${ids.length} findings`}. The agent can read your decision and note from disk.`
  })
}
async function discuss(id: string) {
  const previousNote = savedDecisions.value[id]?.decision === 'discuss' ? savedDecisions.value[id].rationale : ''
  await decide('discuss', [id], previousNote)
  if (error.value) return
  discussion.value = id
  discussionNote.value = previousNote
  await nextTick()
  document.getElementById(`discussion-${id}`)?.focus()
}
async function copyHandoff() {
  await guarded(async () => {
    await refresh()
    handoffOpen.value = true
    try {
      await navigator.clipboard.writeText(handoff.value)
      notice.value = 'Handoff copied. Paste it into your agent chat to continue with these saved decisions.'
    } catch {
      notice.value = 'Select and copy the handoff text below, then paste it into your agent chat.'
    }
  })
}
async function approve() {
  await guarded(async () => {
    await invoke('approve', { run_id: run.value.id, draft_binding: view.value.approval_binding })
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
    <details class="walkthrough">
      <summary>How this works — what you do in the editor and in chat</summary>
      <p><strong>Ask the agent to prepare a stage → review here → approve the draft → ask the agent to continue.</strong></p>
      <ol>
        <li>Confirm the campaign server and session, then click <strong>Load / refresh</strong>. Select a run on the left and check its selected inputs. Existing pilots do not need <strong>Initialize record</strong>.</li>
        <li>Read the outputs using the <strong>Read …</strong> buttons. Evidence previews appear below this workspace.</li>
        <li>Use <strong>Approve</strong>, <strong>Reject</strong>, or <strong>Discuss</strong> on each card. Each click saves your decision. Discuss also opens an optional note for your question or intended wording. Checkboxes only select cards for bulk actions.</li>
        <li>Apply only selected, approved replacements. Ask the agent to check the resulting draft. When all checks and findings are resolved, read every output and click <strong>I have reviewed this draft — approve</strong>. A clean audit still needs your sign-off.</li>
        <li>Click <strong>Copy handoff for agent</strong> and paste it into your agent chat. The agent reads the saved decisions, discusses open questions, and applies approved changes. Then return here and click <strong>Load / refresh</strong>.</li>
      </ol>
      <p><strong>Approval does not launch the next stage yet.</strong> <strong>Resume status</strong> reports progress. <strong>Execute / show native task</strong> runs an existing CLI task or displays an agent task; it does not launch Claude/Codex or create the next stage. Results appear under <strong>CLI / agent interchange commands</strong> below. You do not need to edit JSON for normal review.</p>
      <p>After capture, the next stage is <strong>identify</strong>: the agent checks speaker names against the player roster and proposes transcript corrections. You review the identities and wording. A player's identity does not establish which character spoke every line.</p>
      <p>Example chat request: “Continue the Phandalin pilot in its isolated cycle-pilot directory. Read its saved workflow state, prepare the next stage, and stop at the next human review.” Name the campaign and session when switching agents.</p>
      <p>Stages appear when their runs are created: capture → identify → events → remove-recap → extract → voice-smooth → no-mech → plan → narrate → release → memory → prepare-next. A <strong>pending_agent</strong> run needs agent work; a <strong>generated</strong> run is a draft; an <strong>approved</strong> run has your sign-off. Stale inputs require refreshed work.</p>
    </details>
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
        <p><strong>Selected input scope:</strong> <span v-for="(input, index) in run.selection" :key="input"><span v-if="index">; </span><code>{{ input }}</code></span></p>
        <p>{{ run.generation.backend }} / {{ run.generation.model || 'backend default' }} / {{ run.generation.effort || 'default effort' }}</p>
        <p>Checks needed: {{ view.missing_checks.join(', ') || 'none' }}. Unresolved: {{ view.unresolved_findings.length }}.</p>
        <p v-for="reason in view.stale_reasons" :key="reason" class="error">{{ reason }}</p>
        <details><summary>Resolved task, inputs, selection and generation metadata</summary><pre>{{ JSON.stringify(run, null, 2) }}</pre></details>
        <div class="controls">
          <button v-for="e in run.outputs" :key="e.path" @click="showEvidence(e)">Read {{ e.path }} ({{ e.label }})</button>
          <button @click="downloadReview">Export review JSON</button>
          <label>Import reviewed JSON <input type="file" accept="application/json" @change="importReview" /></label>
        </div>
        <div class="review-toolbar" aria-label="Review controls">
          <p>Approve, Reject, or Discuss each finding below. Each button saves immediately. Discuss also lets you add an optional note. A finding decision does not approve the whole draft.</p>
          <button :disabled="busy" @click="copyHandoff">Copy handoff for agent</button>
          <p>Paste the handoff into your agent chat when ready. Saved choices and discussion notes are available to the agent; this page does not launch a conversation.</p>
          <p v-if="notice" role="status">{{ notice }}</p>
          <p v-if="error" role="alert" class="error">{{ error }}</p>
        </div>
        <div v-if="handoffOpen" class="handoff">
          <label>Agent handoff <textarea :value="handoff" readonly rows="8" /></label>
        </div>
        <div class="controls">
          <label>Scene <select v-model="scene" aria-label="Scene"><option value="">All scenes</option><option v-for="s in scenes" :key="s">{{ s }}</option></select></label>
          <button :disabled="busy" @click="chosen = rows.map((f: any) => f.id)">Select displayed findings</button>
          <button :disabled="busy" @click="chosen = []">Clear selection</button>
        </div>
        <details class="bulk-actions">
          <summary>Bulk actions · {{ chosen.length }} selected</summary>
          <p>Checkboxes select findings for these actions. Each selected finding gets its own saved decision.</p>
          <label>Optional note for selected findings <textarea v-model="rationale" rows="2" /></label>
          <label>Discussion group (optional) <input v-model="group" /></label>
          <div class="controls">
            <button :disabled="busy || !chosen.length" @click="decide('approve')">Approve selected findings</button>
            <button :disabled="busy || !chosen.length" @click="decide('reject')">Reject selected findings</button>
            <button :disabled="busy || !chosen.length" @click="decide('discuss')">Discuss selected findings</button>
            <button :disabled="busy || !chosen.length" @click="apply">Apply selected approved changes</button>
          </div>
        </details>
        <article v-for="f in rows" :key="f.id" :aria-label="`Finding ${f.id}`">
          <header class="finding-header">
            <h4>{{ f.location }}<span v-if="f.scene"> · {{ f.scene }}</span></h4>
            <strong class="decision-state">{{ decisionLabel(savedDecisions[f.id]?.decision) }}</strong>
          </header>
          <small>{{ f.id }}</small>
          <p>{{ f.description }}</p><p>Proposed action: {{ f.proposed_action }}</p>
          <div v-if="f.change" class="change-comparison">
            <div><h5>Current draft</h5><pre>{{ f.change.before }}</pre></div>
            <div><h5>Proposed replacement</h5><pre>{{ f.change.after }}</pre></div>
          </div>
          <div class="finding-decisions">
            <div><button :disabled="busy" :aria-pressed="savedDecisions[f.id]?.decision === 'approve'" @click="decide('approve', [f.id], '')">Approve</button><p>{{ f.consequences.approve }}</p></div>
            <div><button :disabled="busy" :aria-pressed="savedDecisions[f.id]?.decision === 'reject'" @click="decide('reject', [f.id], '')">Reject</button><p>{{ f.consequences.reject }}</p></div>
            <div><button :disabled="busy" :aria-pressed="savedDecisions[f.id]?.decision === 'discuss'" @click="discuss(f.id)">Discuss</button><p>{{ f.consequences.discuss }}</p></div>
          </div>
          <p class="review-hint">You can change a saved decision using any of these buttons. A highlighted button marks the saved choice; it does not lock the other choices.</p>
          <div v-if="discussion === f.id" class="discussion-editor">
            <label :for="`discussion-${f.id}`">Optional question or intended wording for the agent</label>
            <textarea :id="`discussion-${f.id}`" v-model="discussionNote" rows="3" placeholder="Explain what needs discussion or suggest different wording." />
            <button :disabled="busy" @click="decide('discuss', [f.id], discussionNote)">Save note</button>
            <button :disabled="busy" @click="discussion = ''">Close</button>
            <p>Saving keeps this finding unresolved and makes your note available to the agent.</p>
          </div>
          <p v-if="savedDecisions[f.id]" class="saved-decision">Saved {{ decisionLabel(savedDecisions[f.id].decision) }}: {{ savedDecisions[f.id].rationale }}</p>
          <details v-if="f.rule"><summary>Rule and source reference</summary><p>{{ f.rule.reference }} · {{ f.rule.scope }}</p><code>{{ f.rule.authority.path }}</code></details>
          <div class="controls">
            <button :disabled="busy" @click="showEvidence(f.evidence)">Read evidence</button>
            <label><input v-model="chosen" type="checkbox" :value="f.id" :disabled="busy" /> Select {{ f.id }} for bulk actions</label>
          </div>
        </article>
        <div class="draft-approval">
          <h4>Whole-draft sign-off</h4>
        <button :disabled="busy" @click="guarded(async () => { result = JSON.stringify(await invoke('execute', { run_id: run.id }), null, 2); await refresh() })">Execute / show native task</button>
        <button :disabled="busy" @click="guarded(async () => { result = JSON.stringify(await invoke('resume'), null, 2); await refresh() })">Resume status</button>
        <p>A completed check does not approve a draft. Read every output before signing off.</p>
        <button :disabled="busy" @click="approve">I have reviewed this draft — approve</button>
        <button :disabled="busy" @click="guarded(async () => { await invoke('select-version', { run_id: run.id }); await refresh() })">Select approved version for downstream work</button>
        </div>
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
.cycle { padding: 1.5rem; min-width: 0; overflow-wrap: anywhere; } .controls { display: flex; gap: .8rem; flex-wrap: wrap; align-items: end; margin: 1rem 0; }
label { display: block; } input:not([type=checkbox]), select, textarea { display: block; padding: .4rem; }
.workspace { display: grid; grid-template-columns: 15rem minmax(0, 1fr); gap: 1.5rem; }
nav button { display: block; width: 100%; text-align: left; padding: .6rem; margin-bottom: .4rem; }
article { border: 1px solid #8886; padding: 1rem; margin: .8rem 0; } .error { color: #cf4d4d; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 35rem; overflow: auto; } textarea { width: 100%; }
button { cursor: pointer; max-width: 100%; overflow-wrap: anywhere; } button:disabled { cursor: not-allowed; opacity: .5; }
.review-toolbar { border: 1px solid #8886; border-radius: .4rem; padding: 1rem; margin: 1rem 0; }
.review-toolbar p { margin: .6rem 0; }
.finding-header { display: flex; flex-wrap: wrap; gap: 1rem; justify-content: space-between; align-items: baseline; }
h4, h5 { margin: .3rem 0; } h5 { font-size: 1rem; }
.decision-state { border: 1px solid #8886; border-radius: 1rem; padding: .2rem .7rem; }
.change-comparison, .finding-decisions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1rem; margin: 1rem 0; }
.finding-decisions { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.finding-decisions button { width: 100%; min-height: 2.5rem; font-weight: 600; }
.finding-decisions button[aria-pressed=true] { outline: 2px solid currentColor; outline-offset: 2px; }
.finding-decisions p { font-size: .9rem; }
.change-comparison pre { border-left: 3px solid #8886; padding: .7rem; margin: .4rem 0; }
.discussion-editor { border: 1px solid #8886; padding: 1rem; }
textarea { box-sizing: border-box; }
.bulk-actions, .draft-approval { border: 1px solid #8886; padding: 1rem; margin: 1rem 0; }
article code, article small { overflow-wrap: anywhere; }
@media (max-width: 800px) { .change-comparison, .finding-decisions { grid-template-columns: 1fr; } }
@media (max-width: 800px) { .workspace { grid-template-columns: 1fr; } }
</style>
