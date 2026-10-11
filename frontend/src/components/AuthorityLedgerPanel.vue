<script setup lang="ts">
// The reviewed-authority ledger (spec 035): GM rulings staged, proposed and applied through the
// `summary_native authority` CLI. Lives on its own Rulings page so the Summary-native build flow stays
// uncluttered. The planning-notes audience preview stays on Summary-native: it feeds the planning prose step.
import { ref, onMounted } from 'vue'
import { apiFetch } from '../api/client'

const props = defineProps<{ /** The summaries directory a source-correction proposal reads. */ summariesDir: string }>()
const BASE = '/api/grounding/summary-native'

// ── Reviewed authority (all state is reconstructed from CLI-backed routes) ──
// These fields deliberately stay per-page.  Records, proposals, receipts and
// recovery journals live in the campaign authority store; the browser only
// holds an explicit command the GM is about to send.
interface AuthorityEnvelope<T = Record<string, unknown>> {
  ok: boolean; code: string; message: string; artifacts: string[]; data: T
}
interface AuthorityStatus {
  state?: 'absent' | 'initialized' | 'pending'; campaign?: string; revision?: number; sha256?: string; records?: number
  conflicts?: number; pending_transaction?: string | { id?: string } | null
  stale_projections?: Array<string | { doc: string; draft?: string; reason: string }>
}
interface AuthorityRecord {
  id: string; revision?: number; status?: string; subject?: { id?: string } | string
  proposal_id?: string; applied_receipt?: string; replacement_fact?: string
  classification?: string; audience?: string | string[]
}
interface AuthorityConflict {
  id: string; basis: string; status: string; record_ids: string[]; projections: string[]
  resolution_record?: string
  records?: Array<{ id: string; source: string; anchor: string; normalized_value?: string | number | boolean; effective: Record<string, unknown>; projections: string[] }>
}

const authorityStatus = ref<AuthorityStatus | null>(null)
const authorityRecords = ref<AuthorityRecord[]>([])
const authorityConflicts = ref<AuthorityConflict[]>([])
const authorityHistory = ref<Record<string, unknown> | null>(null)
const authorityMessage = ref('')
const authorityError = ref('')
const authorityBusy = ref(false)
const authorityRecordFile = ref('')
const authorityStageId = ref('')
const authorityStageSha = ref('')
const authorityProposalId = ref('')
const authorityProposalSha = ref('')
const authorityProposalArtifacts = ref<string[]>([])
const authorityDiff = ref('')
const authorityProposalRecordId = ref('')
const authoritySelectedId = ref('')
const authorityReason = ref('')
const authorityResolutionRecordFile = ref('')
const authorityConflictId = ref('')
const authorityConflictRecordIds = ref('')
const authorityConflictBasis = ref<'human_identified' | 'prose_candidate'>('human_identified')

function authorityData(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {}
}

function authorityEnvelopeFromSse(body: string): AuthorityEnvelope | null {
  // The shared subprocess runner streams stdout in JSON-encoded SSE data
  // chunks.  Authority CLI stdout itself is one JSON envelope; locate that
  // envelope without assigning any policy meaning to its fields.
  const chunks: string[] = []
  for (const frame of body.split('\n\n')) {
    if (frame.startsWith('event: command') || frame.startsWith('event: done')) continue
    for (const line of frame.split('\n')) {
      if (!line.startsWith('data: ')) continue
      try {
        const value = JSON.parse(line.slice(6))
        if (typeof value === 'string' && !value.startsWith('$')) chunks.push(value)
      } catch { /* a malformed progress frame remains ordinary command output */ }
    }
  }
  const joined = chunks.join('')
  for (const candidate of [joined, ...chunks.slice().reverse()]) {
    try {
      const value = JSON.parse(candidate)
      if (value && typeof value === 'object' && 'ok' in value && 'code' in value) {
        return value as AuthorityEnvelope
      }
    } catch { /* keep looking through chunk boundaries */ }
  }
  return null
}

async function refreshAuthority() {
  authorityError.value = ''
  try {
    const status = await apiFetch<AuthorityEnvelope<AuthorityStatus>>(`${BASE}/authority/status`)
    if (status.data.state === 'absent') {
      authorityStatus.value = null
      authorityRecords.value = []
      return
    }
    authorityStatus.value = status.data
    try {
      const records = await apiFetch<AuthorityEnvelope<{ records?: AuthorityRecord[] }>>(`${BASE}/authority/records`)
      authorityRecords.value = Array.isArray(records.data.records) ? records.data.records : []
    } catch (e) {
      // Recovery status remains actionable even if the separate list command
      // refuses because the same transaction blocks it.
      authorityRecords.value = []
      authorityError.value = e instanceof Error ? e.message : String(e)
    }
    try {
      const conflicts = await apiFetch<AuthorityEnvelope<{ conflicts?: AuthorityConflict[] }>>(`${BASE}/authority/conflicts`)
      authorityConflicts.value = Array.isArray(conflicts.data.conflicts) ? conflicts.data.conflicts : []
    } catch (e) {
      authorityConflicts.value = []
      authorityError.value = e instanceof Error ? e.message : String(e)
    }
  } catch (e) {
    authorityStatus.value = null
    authorityRecords.value = []
    authorityConflicts.value = []
    authorityError.value = e instanceof Error ? e.message : String(e)
  }
}

async function loadConflictHistory(conflictId: string) {
  authorityError.value = ''
  try {
    const result = await apiFetch<AuthorityEnvelope<Record<string, unknown>>>(`${BASE}/authority/conflicts/${encodeURIComponent(conflictId)}/history`)
    authorityHistory.value = result.data
  } catch (e) {
    authorityHistory.value = null
    authorityError.value = e instanceof Error ? e.message : String(e)
  }
}

async function runAuthority(path: string, payload: Record<string, unknown> = {}) {
  authorityBusy.value = true
  authorityError.value = ''
  authorityMessage.value = ''
  try {
    const response = await fetch(`${BASE}/authority/${path}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    })
    const body = await response.text()
    const result = authorityEnvelopeFromSse(body)
    if (!response.ok) throw new Error(result?.message || body || `API ${response.status}`)
    if (!result) throw new Error('authority command did not return its JSON result')
    if (!result.ok) throw new Error(result.message)
    authorityMessage.value = result.message
    const data = authorityData(result.data)
    if (path === 'records/stage') {
      authorityStageId.value = String(data.id ?? '')
      authorityStageSha.value = String(data.sha256 ?? '')
    }
    if (path.startsWith('records/stages/') && path.endsWith('/apply')) {
      // The real envelope names the revised record and its newly committed
      // revision.  Discard the one-time stage binding after it is consumed so
      // the page cannot offer a stale second apply.
      authorityStageId.value = ''
      authorityStageSha.value = ''
      authoritySelectedId.value = typeof data.id === 'string' ? data.id : authoritySelectedId.value
    }
    if (path.endsWith('/propose')) {
      authorityProposalRecordId.value = authoritySelectedId.value
      authorityProposalId.value = String(data.id ?? data.proposal_id ?? '')
      authorityProposalSha.value = String(data.proposal_sha256 ?? '')
      authorityDiff.value = typeof data.diff === 'string' ? data.diff : ''
    }
    authorityProposalArtifacts.value = Array.isArray(result.artifacts) ? result.artifacts : []
    await refreshAuthority()
  } catch (e) {
    authorityError.value = e instanceof Error ? e.message : String(e)
  } finally {
    authorityBusy.value = false
  }
}

function selectAuthorityRecord(recordId: string) {
  authoritySelectedId.value = recordId
  if (authorityProposalRecordId.value !== recordId) {
    authorityProposalId.value = ''
    authorityProposalSha.value = ''
    authorityProposalArtifacts.value = []
    authorityProposalRecordId.value = ''
    authorityDiff.value = ''
  }
}

function proposeAuthority(recordId: string) {
  selectAuthorityRecord(recordId)
  authorityProposalId.value = ''
  authorityProposalSha.value = ''
  authorityProposalArtifacts.value = []
  authorityProposalRecordId.value = ''
  authorityDiff.value = ''
  return runAuthority(`records/${encodeURIComponent(recordId)}/propose`, { summaries_dir: props.summariesDir })
}

function pendingAuthorityTransactionId() {
  const pending = authorityStatus.value?.pending_transaction
  return typeof pending === 'string' ? pending : pending?.id ?? ''
}

function staleProjectionLabel(stale: string | { doc: string; draft?: string; reason: string }) {
  if (typeof stale === 'string') return stale
  return `${stale.doc}: ${stale.reason}`
}

async function loadAuthorityHistory(recordId: string) {
  authoritySelectedId.value = recordId
  authorityError.value = ''
  try {
    const result = await apiFetch<AuthorityEnvelope<Record<string, unknown>>>(`${BASE}/authority/records/${encodeURIComponent(recordId)}/history`)
    authorityHistory.value = result.data
  } catch (e) {
    authorityHistory.value = null
    authorityError.value = e instanceof Error ? e.message : String(e)
  }
}

const lines = (t: string) => t.split('\n').map(l => l.trim()).filter(Boolean)

onMounted(refreshAuthority)
</script>

<template>
  <!-- Authority: the CLI owns every decision and mutation.  This panel only
       displays its envelopes and makes the GM provide the approval digest. -->
  <div class="form-section authority" data-test="authority-panel">
    <h3 class="step">Reviewed authority</h3>
    <div v-if="authorityStatus" class="counts">
      <span>ledger revision {{ authorityStatus.revision }}</span>
      <span><code>{{ authorityStatus.sha256 }}</code></span>
      <span>{{ authorityStatus.records ?? 0 }} record(s)</span>
      <span v-if="authorityStatus.pending_transaction" class="bad">recovery required</span>
    </div>
    <span v-else class="field-help">No authority ledger is initialized for this campaign.</span>
    <button v-if="!authorityStatus" class="btn-neutral btn-sm" :disabled="authorityBusy"
      @click="runAuthority('init')">Initialize authority ledger</button>
    <button v-else class="btn-neutral btn-sm" :disabled="authorityBusy" @click="refreshAuthority">Refresh authority</button>

    <div v-if="authorityStatus" class="authority-actions">
      <div class="field">
        <label class="field-label">Reviewed record file</label>
        <input class="field-input" v-model="authorityRecordFile" placeholder="docs/authority/records/earthstone.yaml" />
        <button class="btn-neutral btn-sm" :disabled="authorityBusy || !authorityRecordFile.trim()"
          @click="runAuthority('records/stage', { record_file: authorityRecordFile })">Stage record revision</button>
      </div>
      <div v-if="authorityStageId && authorityStageSha" class="panel authority-approval">
        <span>Staged <code>{{ authorityStageId }}</code> with digest <code>{{ authorityStageSha }}</code>.</span>
        <button class="btn-neutral btn-sm" :disabled="authorityBusy"
          @click="runAuthority(`records/stages/${encodeURIComponent(authorityStageId)}/apply`, {
            stage_sha256: authorityStageSha, expected_ledger_sha256: authorityStatus?.sha256,
          })">Apply staged revision</button>
      </div>

      <div v-if="authorityStatus.pending_transaction" class="panel authority-recovery">
        <span class="bad">A transaction is incomplete. Recovery only resumes its already-approved bytes.</span>
        <button class="btn-neutral btn-sm" :disabled="authorityBusy"
          @click="runAuthority(`transactions/${encodeURIComponent(pendingAuthorityTransactionId())}/recover`)">Recover transaction</button>
      </div>

      <table v-if="authorityRecords.length" class="drafts authority-records">
        <thead><tr><th>Record</th><th>Status</th><th>Revision</th><th></th></tr></thead>
        <tbody>
          <tr v-for="record in authorityRecords" :key="record.id">
            <td><code>{{ record.id }}</code></td>
            <td>{{ record.status }}</td><td>{{ record.revision }}</td>
            <td class="authority-buttons">
              <button class="btn-neutral btn-sm" :disabled="authorityBusy" @click="loadAuthorityHistory(record.id)">History</button>
              <button class="btn-neutral btn-sm" :disabled="authorityBusy"
                @click="proposeAuthority(record.id)">Propose source correction</button>
              <button class="btn-neutral btn-sm" :disabled="authorityBusy"
                @click="selectAuthorityRecord(record.id)">Select</button>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="authorityProposalSha && authorityDiff && authoritySelectedId === authorityProposalRecordId" class="panel authority-approval">
        <span>Proposal <code>{{ authorityProposalId }}</code> is bound to digest <code>{{ authorityProposalSha }}</code>.</span>
        <label class="field-label">Proposal digest to approve</label>
        <input class="field-input" :value="authorityProposalSha" readonly aria-label="Proposal digest to approve" />
        <button class="btn-neutral btn-sm" :disabled="authorityBusy || !authorityDiff"
          @click="runAuthority(`records/${encodeURIComponent(authoritySelectedId)}/apply`, { proposal_sha256: authorityProposalSha })">Apply displayed correction</button>
      </div>
      <pre v-if="authorityDiff" class="authority-diff" aria-label="Exact proposed source diff">{{ authorityDiff }}</pre>
      <span v-if="authorityProposalArtifacts.length" class="field-help">Proposal artifacts: {{ authorityProposalArtifacts.join(', ') }}</span>

      <!-- One reason serves withdraw, retire, dismiss and record-a-finding, so it stays
           visible with no record selected: conflicts are ruled on without one. -->
      <div class="field">
        <label class="field-label">Reason</label>
        <input class="field-input" v-model="authorityReason" placeholder="Reason for requesting a safe reversal" />
        <span class="field-help">Required to withdraw or retire a record, dismiss a conflict, or record a human finding.</span>
      </div>
      <div v-if="authoritySelectedId" class="field authority-withdraw">
        <label class="field-label">Selected record: {{ authoritySelectedId }}</label>
        <button class="btn-neutral btn-sm" :disabled="authorityBusy || !authorityReason.trim()"
          @click="runAuthority(`records/${encodeURIComponent(authoritySelectedId)}/withdraw`, { reason: authorityReason })">Request withdrawal</button>
        <button class="btn-neutral btn-sm" :disabled="authorityBusy || !authorityReason.trim() || !authorityStatus?.sha256"
          @click="runAuthority(`records/${encodeURIComponent(authoritySelectedId)}/retire`, {
            reason: authorityReason, expected_revision: authorityRecords.find(r => r.id === authoritySelectedId)?.revision,
            expected_ledger_sha256: authorityStatus?.sha256,
          })">Retire record</button>
      </div>
      <div class="authority-conflicts">
        <h4>Authority conflicts</h4>
        <span v-if="!authorityConflicts.length" class="field-help">No unresolved or historical conflicts are recorded.</span>
        <table v-else class="drafts authority-records">
          <thead><tr><th>Finding</th><th>Compared source, value, scope</th><th>Projection</th><th>Status</th><th></th></tr></thead>
          <tbody>
            <tr v-for="conflict in authorityConflicts" :key="conflict.id">
              <td><code>{{ conflict.id }}</code><br /><span>{{ conflict.basis }}</span></td>
              <td><template v-if="conflict.records?.length"><div v-for="record in conflict.records" :key="record.id"><code>{{ record.id }}</code> {{ record.source }}#{{ record.anchor }} = {{ record.normalized_value ?? 'unstructured' }} ({{ JSON.stringify(record.effective) }})</div></template><template v-else>{{ conflict.record_ids.join(', ') }}</template></td><td>{{ conflict.projections.join(', ') }}</td><td>{{ conflict.status }}</td>
              <td class="authority-buttons">
                <button class="btn-neutral btn-sm" :disabled="authorityBusy" @click="loadConflictHistory(conflict.id)">History</button>
                <button v-if="conflict.status === 'open'" class="btn-neutral btn-sm" :disabled="authorityBusy || !authorityResolutionRecordFile.trim() || !authorityStatus?.sha256"
                  @click="runAuthority(`conflicts/${encodeURIComponent(conflict.id)}/resolve`, { resolution_record_file: authorityResolutionRecordFile, expected_ledger_sha256: authorityStatus?.sha256 })">Resolve with ruling</button>
                <button v-if="conflict.status === 'open'" class="btn-neutral btn-sm" :disabled="authorityBusy || !authorityReason.trim() || !authorityStatus?.sha256"
                  @click="runAuthority(`conflicts/${encodeURIComponent(conflict.id)}/dismiss`, { reason: authorityReason, expected_ledger_sha256: authorityStatus?.sha256 })">Dismiss conflict</button>
              </td>
            </tr>
          </tbody>
        </table>
        <div class="field">
          <label class="field-label">Applied resolution ruling file</label>
          <input class="field-input" v-model="authorityResolutionRecordFile" placeholder="docs/authority/records/gate-resolution.yaml" />
        </div>
        <div class="field">
          <label class="field-label">Record a human finding</label>
          <input class="field-input" v-model="authorityConflictId" placeholder="contradictory-gate-account" />
          <textarea class="field-input" v-model="authorityConflictRecordIds" placeholder="record IDs, one per line"></textarea>
          <select class="field-input" v-model="authorityConflictBasis"><option value="human_identified">Human identified</option><option value="prose_candidate">Prose candidate</option></select>
          <button class="btn-neutral btn-sm" :disabled="authorityBusy || !authorityConflictId.trim() || lines(authorityConflictRecordIds).length < 2 || !authorityReason.trim() || !authorityStatus?.sha256"
            @click="runAuthority('conflicts/identify', { id: authorityConflictId, record_ids: lines(authorityConflictRecordIds), basis: authorityConflictBasis, reason: authorityReason, expected_ledger_sha256: authorityStatus?.sha256 })">Record conflict</button>
        </div>
      </div>
      <pre v-if="authorityHistory" class="authority-history">{{ JSON.stringify(authorityHistory, null, 2) }}</pre>
      <span v-if="authorityStatus.stale_projections?.length" class="field-error">Stale projections: {{ authorityStatus.stale_projections.map(staleProjectionLabel).join(', ') }}</span>
    </div>
    <span v-if="authorityMessage" class="field-help ok">{{ authorityMessage }}</span>
    <span v-if="authorityError" class="field-error">{{ authorityError }}</span>
  </div>
</template>

<style scoped>
/* The same field and table styles as the Summary-native page. The app's global reset zeroes every margin,
   so the panel spaces its own parts. */
.step { font-size: 12px; font-weight: 700; color: var(--text); margin-bottom: 8px; }
.field { margin-bottom: 10px; }
.field-label { display: block; font-size: 11px; font-weight: 600; color: var(--text-sub); margin-bottom: 3px; }
.field-input {
  width: 100%; padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-base);
  color: var(--text); font-family: var(--mono); font-size: 11px;
  outline: none; box-sizing: border-box;
}
.field-input:focus { border-color: var(--mauve); }
.field-help { display: block; font-size: 10px; color: var(--text-muted); margin-top: 3px; }
.field-error { display: block; font-size: 11px; color: var(--red); margin-top: 4px; }
.panel { padding: 10px; background: var(--bg-mantle); border-radius: 4px; font-size: 11px; color: var(--text-sub); }
.counts { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 8px; font-size: 11px; color: var(--text-sub); }
.counts code, .drafts code, .panel code { font-family: var(--mono); font-size: 10px; }
.ok { color: var(--green); }
.bad { color: var(--red); }
.drafts { border-collapse: collapse; font-size: 11px; color: var(--text-sub); margin-top: 6px; }
.drafts th, .drafts td { text-align: left; padding: 3px 14px 3px 0; }
.drafts th { font-weight: 600; color: var(--text); }
.authority-actions { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; }
.authority-actions .field { margin-bottom: 0; }
.authority-actions .btn-neutral { margin: 6px 6px 0 0; }
.authority-buttons { white-space: nowrap; }
.authority > .btn-neutral { margin-top: 6px; }
.authority .field > .field-input + .field-input { margin-top: 6px; }
.authority .field > .field-input + .btn-neutral { margin-top: 6px; }
.authority-approval, .authority-recovery { display: flex; flex-direction: column; align-items: flex-start; gap: 6px; }
.authority-approval .field-input { width: 100%; }
.authority-approval .btn-neutral, .authority-recovery .btn-neutral { margin: 0; }
.authority-conflicts { display: flex; flex-direction: column; gap: 8px; }
.authority-conflicts h4 { font-size: 11px; font-weight: 700; color: var(--text); }
.authority-conflicts .field { margin-bottom: 0; }
.authority-conflicts .drafts { margin-top: 0; }
.authority-diff, .authority-history { max-height: 260px; overflow: auto; white-space: pre-wrap; padding: 8px; background: var(--bg-base); border: 1px solid var(--bg-surface1); border-radius: 4px; color: var(--text-sub); font: 10px var(--mono); }
</style>
