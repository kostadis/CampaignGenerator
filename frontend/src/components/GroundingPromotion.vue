<script setup lang="ts">
import { computed, ref, watch } from 'vue'

type Num = number | ''

interface Member {
  path?: string
  source?: string
  destination?: string
  document_id?: string
  kind?: string
  sha256?: string
  size?: number
}

interface Change {
  path: string
  kind: string
  before_sha256?: string | null
  after_sha256?: string | null
  unified_diff?: string | null
}

interface Gate {
  gate?: string
  state?: string
  code?: string | null
  message?: string
}

interface Preview {
  eligible?: boolean
  preview_sha256?: string
  bundle_digest?: string
  manifest?: BundleManifest | Member[]
  bundle?: BundleManifest
  selection?: BundleManifest
  members?: Member[]
  changes?: Change[]
  gates?: Gate[]
  refusal_codes?: string[]
  claims?: { state?: string; message?: string } | string
}

interface BundleManifest {
  members?: Member[]
  documents?: Member[]
  timeline?: Member
  references?: Member[]
  retained_records?: Member[]
  dependencies?: Member[]
}

interface Envelope {
  ok: boolean
  code: string
  message: string
  data: { selection: BundleManifest | null; preview: Preview; destination: Record<string, unknown> | null }
}

const props = defineProps<{ since?: number | null; until?: number | null; reviewId?: string; checkReportPath?: string }>()
const emit = defineEmits<{ reviewChanged:[value:string] }>()
const since = ref<Num>(props.since ?? '')
const until = ref<Num>(props.until ?? '')
const review = ref(props.reviewId ?? '')
const checkReport = ref(props.checkReportPath ?? '')
const busy = ref(false)
const feedback = ref('')
const error = ref('')
const preview = ref<Preview | null>(null)
const selection = ref<BundleManifest | null>(null)
const destination = ref<Record<string, unknown> | null>(null)
const requestId = ref('')
const operation = ref('')
const migrationPlan = ref('')
const inspection = ref<Record<string, unknown> | null>(null)
const inspectionCode = ref('')
const consentConsumed = ref(false)

const ready = computed(() => Number.isInteger(since.value) && Number.isInteger(until.value)
  && Number(since.value) <= Number(until.value) && review.value.trim() !== '' && checkReport.value.trim() !== '')

const members = computed<Member[]>(() => {
  const value = preview.value
  if (!value) return []
  if (Array.isArray(value.manifest)) return value.manifest
  const manifest = selection.value ?? value.manifest ?? value.bundle ?? value.selection
  if (manifest?.members) return manifest.members
  if (manifest) return [
    ...(manifest.documents ?? []).map(member => ({ ...member, kind: member.kind ?? 'document' })),
    ...(manifest.timeline ? [{ ...manifest.timeline, kind: manifest.timeline.kind ?? 'timeline' }] : []),
    ...(manifest.references ?? []).map(member => ({ ...member, kind: member.kind ?? 'reference' })),
    ...(manifest.retained_records ?? []).map(member => ({ ...member, kind: member.kind ?? 'retained record' })),
    ...(manifest.dependencies ?? []).map(member => ({ ...member, kind: member.kind ?? 'dependency' })),
  ]
  return value.members ?? []
})
const changes = computed(() => preview.value?.changes ?? [])
const gates = computed(() => preview.value?.gates ?? [])
const blockers = computed(() => gates.value.filter(gate => gate.state !== 'passed'))
const sourceStaleness = computed(() => gates.value.filter(gate => {
  const text = `${gate.gate ?? ''} ${gate.code ?? ''} ${gate.message ?? ''}`.toLowerCase()
  return text.includes('source') || text.includes('signoff') || text.includes('review') || text.includes('authority')
}))
const destinationStaleness = computed(() => gates.value.filter(gate => {
  const text = `${gate.gate ?? ''} ${gate.code ?? ''} ${gate.message ?? ''}`.toLowerCase()
  return text.includes('destination') || text.includes('live') || text.includes('preview stale')
}))
const sourceFreshness = computed(() => sourceStaleness.value.length
  ? (sourceStaleness.value.every(gate => gate.state === 'passed') ? 'Current' : 'Stale') : 'Unknown')
const destinationFreshness = computed(() => destinationStaleness.value.length
  ? (destinationStaleness.value.every(gate => gate.state === 'passed') ? 'Current' : 'Stale') : 'Unknown')
const destinationIdentity = computed(() => {
  const value = destination.value
  if (!value) return ''
  const identity = value.live_digest ?? value.generation_id ?? value.activation_id
  return typeof identity === 'string' ? identity : ''
})
const claims = computed(() => {
  if (preview.value?.claims) {
    return typeof preview.value.claims === 'string'
      ? { state: preview.value.claims, message: '' }
      : preview.value.claims
  }
  const gate = gates.value.find(item => (item.gate ?? '').toLowerCase() === 'claims')
  return gate ? { state: gate.state, message: gate.message ?? '' } : null
})
const operationOutcome = computed(() => {
  const data:any = inspection.value ?? {}
  const raw = data.state ?? data.status ?? data.outcome ?? inspectionCode.value
  return typeof raw === 'string' && raw ? raw.replaceAll('_','-').toLowerCase() : ''
})
const priorIdentity = computed(() => {
  const data:any=inspection.value??{}
  return data.prior_identity ?? data.before_sha256 ?? data.activation?.prior_generation_id ?? data.receipt?.prior_generation_id ?? ''
})
const newIdentity = computed(() => {
  const data:any=inspection.value??{}
  return data.new_identity ?? data.after_sha256 ?? data.activation?.generation_id ?? data.receipt?.generation_id ?? data.activation?.activation_id ?? ''
})

watch(() => props.since, value => { if (typeof value === 'number') since.value = value })
watch(() => props.until, value => { if (typeof value === 'number') until.value = value })
watch(() => props.reviewId, value => { if (value !== undefined && value !== review.value) review.value = value })
watch(() => props.checkReportPath, value => { if (value !== undefined) checkReport.value = value })

async function runPreview() {
  if (!ready.value) return
  busy.value = true
  feedback.value = 'Requesting an exact read-only preview…'
  error.value = ''
  preview.value = null
  consentConsumed.value = false
  selection.value = null
  destination.value = null
  try {
    const response = await fetch('/api/grounding/summary-native/promotion/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        since: Number(since.value), until: Number(until.value),
        review: review.value.trim(), check_report: checkReport.value.trim(),
      }),
    })
    const envelope = await response.json() as Envelope
    if (!envelope.data?.preview) throw new Error('Preview response omitted preview data.')
    selection.value = envelope.data.selection
    preview.value = envelope.data.preview
    destination.value = envelope.data.destination
    feedback.value = envelope.message ?? (response.ok ? 'Preview refreshed.' : 'Preview returned blockers.')
    if (!response.ok || envelope.ok === false) error.value = `${envelope.code ? `${envelope.code}: ` : ''}${envelope.message ?? `Request failed (${response.status})`}`
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
    feedback.value = 'Preview request failed.'
  } finally {
    busy.value = false
  }
}

async function invoke(path: string, method = 'POST', body?: Record<string, unknown>) {
  busy.value = true
  error.value = ''
  feedback.value = 'Running installed campaign command…'
  try {
    const response = await fetch(`/api/grounding/summary-native/promotion/${path}`, {
      method,
      headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
    const envelope = await response.json()
    inspection.value = envelope.data ?? null
    inspectionCode.value = envelope.code ?? ''
    feedback.value = envelope.message ?? 'Command completed.'
    if (!response.ok || envelope.ok === false) error.value = `${envelope.code ?? 'COMMAND_FAILED'}: ${envelope.message ?? 'Command failed.'}`
    return envelope
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : String(reason)
    feedback.value = 'Command failed.'
    return null
  } finally {
    busy.value = false
  }
}

async function commit() {
  if (!preview.value?.eligible || consentConsumed.value || !preview.value.preview_sha256 || !requestId.value.trim()) return
  consentConsumed.value = true
  const envelope = await invoke('commit', 'POST', {
    since: Number(since.value), until: Number(until.value), review: review.value.trim(),
    check_report: checkReport.value.trim(), preview_sha256: preview.value.preview_sha256,
    request_id: requestId.value.trim(),
  })
  const id = envelope?.data?.operation_id ?? envelope?.data?.activation?.operation_id ?? envelope?.data?.receipt?.operation_id
  if (typeof id === 'string') operation.value = id
}

const operationBody = () => ({ operation: operation.value.trim() })

function label(member: Member) {
  return member.document_id ?? member.kind ?? 'support'
}
</script>

<template>
  <section class="promotion" aria-labelledby="promotion-title" data-test="grounding-promotion-preview">
    <div class="heading">
      <div><h3 id="promotion-title">Whole-bundle promotion preview</h3>
        <p>Read-only preview of all four reviewed documents, the actual timeline, nested references, retained records, and live changes.</p>
      </div>
      <span class="checkpoint">human checkpoint</span>
    </div>

    <div class="inputs">
      <label>Since chapter <input v-model.number="since" type="number" min="0" data-test="promotion-since"></label>
      <label>Until chapter <input v-model.number="until" type="number" min="0" data-test="promotion-until"></label>
      <label>Review ID <input v-model="review" autocomplete="off" data-test="promotion-review" @input="emit('reviewChanged',review)"></label>
      <label>Check report ID or path <input v-model="checkReport" autocomplete="off" data-test="promotion-report"></label>
    </div>
    <p v-if="!ready" class="hint">Choose an explicit ordered range, review, and check report before previewing.</p>
    <button class="btn-neutral" :disabled="busy || !ready" @click="runPreview">
      {{ busy ? 'Previewing…' : 'Preview complete bundle' }}
    </button>
    <span class="feedback" role="status" aria-live="polite">{{ feedback }}</span>
    <p v-if="error" class="error" role="alert">{{ error }}</p>

    <template v-if="preview">
      <div class="summary" :class="preview.eligible ? 'eligible' : 'blocked'">
        <strong>{{ preview.eligible ? 'Eligible preview' : 'Publication blocked' }}</strong>
        <span v-if="preview.preview_sha256">preview <code>{{ preview.preview_sha256 }}</code></span>
        <span v-if="preview.bundle_digest">bundle <code>{{ preview.bundle_digest }}</code></span>
        <span v-if="destinationIdentity">destination <code>{{ destinationIdentity }}</code></span>
      </div>

      <div class="claims" :class="claims?.state === 'passed' || claims?.state === 'complete' ? 'eligible' : 'blocked'">
        <strong>Claims gate: {{ claims?.state ?? 'not_available' }}</strong>
        <span>{{ claims?.message || (claims ? '' : 'No claims result was returned. This is not a passing check.') }}</span>
      </div>

      <div class="staleness">
        <div><strong>Source approval freshness: {{ sourceFreshness }}</strong>
          <span v-for="gate in sourceStaleness" :key="`${gate.gate}:${gate.code}`">{{ gate.message ?? gate.code }}</span></div>
        <div><strong>Destination preview freshness: {{ destinationFreshness }}</strong>
          <span v-for="gate in destinationStaleness" :key="`${gate.gate}:${gate.code}`">{{ gate.message ?? gate.code }}</span></div>
      </div>

      <div v-if="blockers.length || preview.refusal_codes?.length" class="result-block">
        <h4>Blocking conditions</h4>
        <ul><li v-for="gate in blockers" :key="`${gate.gate}:${gate.code}:${gate.message}`"><code>{{ gate.code ?? gate.gate }}</code> {{ gate.message }}</li>
          <li v-for="code in preview.refusal_codes ?? []" :key="code"><code>{{ code }}</code></li></ul>
      </div>

      <div class="result-block"><h4>Complete manifest ({{ members.length }})</h4>
        <table v-if="members.length"><thead><tr><th>Class</th><th>Path</th><th>Destination</th><th>Identity</th></tr></thead>
          <tbody><tr v-for="member in members" :key="`${member.path ?? member.source}:${member.destination}`">
            <td>{{ label(member) }}</td><td><code>{{ member.path ?? member.source }}</code></td>
            <td><code>{{ member.destination ?? '—' }}</code></td><td><code>{{ member.sha256 ?? '—' }}</code><span v-if="member.size !== undefined"> · {{ member.size }} B</span></td>
          </tr></tbody></table><p v-else class="hint">The response contained no manifest members.</p>
      </div>

      <div class="result-block"><h4>Live differences ({{ changes.length }})</h4>
        <article v-for="change in changes" :key="change.path" class="change">
          <div><strong>{{ change.kind }}</strong> <code>{{ change.path }}</code></div>
          <div class="digests"><code>{{ change.before_sha256 ?? 'absent' }}</code> → <code>{{ change.after_sha256 ?? 'absent' }}</code></div>
          <pre v-if="change.unified_diff">{{ change.unified_diff }}</pre>
        </article><p v-if="!changes.length" class="hint">No path changes were returned.</p>
      </div>

      <div class="actions">
        <label>Request ID <input v-model="requestId" autocomplete="off" data-test="promotion-request-id"></label>
        <button class="btn-primary" data-test="promotion-commit" :disabled="busy || consentConsumed || !preview.eligible || !requestId.trim()" @click="commit">Publish exact preview</button>
        <p v-if="consentConsumed" class="hint">This preview consent was consumed by the commit attempt. Refresh the preview before another publication attempt.</p>
      </div>
    </template>

    <div class="result-block controls" data-test="promotion-operations">
      <h4>Publication status, receipts, and recovery</h4>
      <label>Operation ID <input v-model="operation" autocomplete="off" data-test="promotion-operation"></label>
      <div class="button-row">
        <button :disabled="busy" @click="invoke(`status${operation.trim() ? `?operation=${encodeURIComponent(operation.trim())}` : ''}`, 'GET')">Refresh status</button>
        <button :disabled="busy || !operation.trim()" @click="invoke('receipt', 'POST', operationBody())">View receipt</button>
        <button :disabled="busy || !operation.trim()" @click="invoke('recover', 'POST', operationBody())">Recover publication</button>
      </div>
      <h4>Managed bundle migration</h4>
      <label>Plan digest <input v-model="migrationPlan" autocomplete="off" data-test="migration-plan"></label>
      <div class="button-row">
        <button :disabled="busy" @click="invoke('migration/preview')">Preview migration</button>
        <button :disabled="busy || !/^[0-9a-f]{64}$/.test(migrationPlan)" @click="invoke('migration/apply', 'POST', { plan_sha256: migrationPlan })">Apply exact plan</button>
        <button :disabled="busy" @click="invoke('migration/status', 'GET')">Migration status</button>
        <button :disabled="busy" @click="invoke('migration/verify')">Verify migration</button>
        <button :disabled="busy || !operation.trim()" @click="invoke('migration/recover', 'POST', operationBody())">Recover migration</button>
      </div>
      <pre v-if="inspection" data-test="promotion-inspection">{{ JSON.stringify(inspection, null, 2) }}</pre>
      <div v-if="operationOutcome" class="operation-feedback" data-test="promotion-outcome">
        <strong>Current outcome: {{ operationOutcome }}</strong>
        <span v-if="priorIdentity">Prior identity <code>{{ priorIdentity }}</code></span>
        <span v-if="newIdentity">New identity <code>{{ newIdentity }}</code></span>
        <span v-if="operationOutcome.includes('unknown')">The commit result is unknown. Refresh status with this operation ID, then use recovery if the journal remains pending.</span>
        <span v-else-if="operationOutcome.includes('edited-live') || operationOutcome.includes('stale')">Live files changed after preparation. Inspect the new destination, then create and approve a new preview.</span>
        <span v-else-if="operationOutcome.includes('blocked')">The operation remains blocked. Resolve the displayed gate and create a new preview.</span>
        <span v-else-if="operationOutcome.includes('committed')">The exact preview was committed. Inspect its receipt for the durable identities.</span>
        <span v-else-if="operationOutcome.includes('saved') || operationOutcome.includes('prepared')">The operation is durable but has not completed publication.</span>
      </div>
    </div>
  </section>
</template>

<style scoped>
.promotion{min-width:0;max-width:100%;box-sizing:border-box;padding:14px;border:1px solid var(--bg-surface1);border-radius:6px;background:var(--bg-mantle);font-size:11px;color:var(--text-sub);overflow-wrap:anywhere}
.heading{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px 16px}.heading h3{margin:0;color:var(--text);font-size:12px;font-weight:700}.heading p{margin:4px 0 10px;color:var(--text-muted)}
.checkpoint{height:max-content;padding:3px 7px;border-radius:10px;background:var(--yellow);color:var(--bg-base);font-weight:700}.inputs{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(160px,100%),1fr));gap:10px}.inputs label{min-width:0;font-weight:600;color:var(--text-sub)}
input{display:block;width:100%;box-sizing:border-box;margin-top:3px;padding:6px 8px;border:1px solid var(--bg-surface1);border-radius:4px;background:var(--bg-base);color:var(--text);font:11px var(--mono)}
button{margin-top:9px;font-size:11px}button:not([class]){background:var(--bg-surface0);color:var(--text)}.feedback{margin-left:10px;color:var(--text-muted)}.hint{color:var(--text-muted)}.error,.blocked{color:var(--red)}.eligible{color:var(--green)}
.summary,.claims{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px;padding:8px;background:var(--bg-base);border-radius:4px}.summary code{overflow-wrap:anywhere}.staleness{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:10px;margin-top:10px}.staleness>div{min-width:0;display:flex;flex-direction:column;gap:3px;padding:8px;background:var(--bg-base);border-radius:4px}.staleness strong,h4{color:var(--text)}
.result-block{min-width:0;margin-top:14px;overflow:hidden}.result-block h4{margin:0 0 6px}.result-block ul{margin:0;padding-left:18px}.result-block code{font:10px var(--mono);overflow-wrap:anywhere}table{display:block;width:100%;max-width:100%;overflow-x:auto;border-collapse:collapse}th,td{text-align:left;vertical-align:top;padding:5px 8px 5px 0;border-bottom:1px solid var(--bg-surface0)}th{color:var(--text)}
.change{padding:8px 0;border-bottom:1px solid var(--bg-surface0)}.change strong{text-transform:uppercase}.digests{margin-top:4px;color:var(--text-muted);overflow-wrap:anywhere}.change pre{max-height:18rem;overflow:auto;white-space:pre-wrap;padding:8px;background:var(--bg-base);color:var(--text-sub);font:10px var(--mono)}
.actions,.button-row{display:flex;flex-wrap:wrap;align-items:end;gap:8px;margin-top:10px}.actions label,.controls label{min-width:min(280px,100%)}.controls h4:not(:first-child){margin-top:14px}.controls pre{max-height:20rem;overflow:auto;padding:8px;background:var(--bg-base);font:10px var(--mono);white-space:pre-wrap}
.operation-feedback{display:flex;min-width:0;flex-direction:column;gap:4px;margin-top:10px;padding:8px;background:var(--bg-base)}.operation-feedback code{overflow-wrap:anywhere}
</style>
