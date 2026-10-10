<script setup lang="ts">
import { ref, computed, watch, onMounted, type Ref } from 'vue'
import { apiFetch } from '../../api/client'
import { useConfigStore } from '../../stores/config'
import { useGroundingRun } from '../../composables/useGroundingRun'
import PathField from '../../components/shared/PathField.vue'
import RunPanel from '../../components/shared/RunPanel.vue'
import ReviewLauncher from '../../components/ReviewLauncher.vue'

// summary_native (feature 031): grounding-doc drafts built straight from
// reviewed session summaries. This page invokes the `summary_native` CLI and
// reimplements none of it (FR-029). There is no promote button and no rulings
// editor: a draft is reviewed and promoted by hand, and the CLI-only paths
// (registry, canon, out-root) are set once in grounding.yaml, not per run.

const BASE = '/api/grounding/summary-native'
const SYNTH_ENDPOINT = '/api/grounding/summary-native/run/synth'
const DOCS = ['world_state', 'campaign_state', 'party', 'planning'] as const
type Doc = (typeof DOCS)[number]
// Every document is built from the checked notes (specs 033, 034): Extract first, one prose call per section.
// There is no Parts control, no upstream-draft picker and no audit box on this step: those options are retired.
// The documents that select NPCs and render them from the published dossiers (world_state's Key NPCs, planning's NPC Dossiers).
const KEY_NPC_DOCS: readonly Doc[] = ['world_state', 'planning']

const config = useConfigStore()

// ── Persisted fields (grounding.yaml summary_native) ────────────────────────
// Numeric inputs hold '' while a field is being retyped; that must not reach
// the strict schema, so the persisted view of a blank is `undefined` (dropped
// by JSON, leaving the stored value alone) or, for the range, an explicit null.
type Num = number | '' | null

const summariesDir = ref('')
const rangeSince = ref<Num>(null)
const rangeUntil = ref<Num>(null)
const dupThreshold = ref<Num>('')
const recentChapters = ref<Num>('')
const recurringMin = ref<Num>('')

function persisted(r: Ref<Num>, nullable: boolean) {
  return computed<number | null | undefined>({
    get: () => (typeof r.value === 'number' ? r.value : nullable ? null : undefined),
    set: v => { r.value = v === undefined ? '' : v },
  })
}

useGroundingRun('summary_native', {
  summaries_dir: summariesDir,
  range_since: persisted(rangeSince, true),
  range_until: persisted(rangeUntil, true),
  dup_threshold: persisted(dupThreshold, false),
  recent_chapters: persisted(recentChapters, false),
  recurring_min: persisted(recurringMin, false),
})

// ── Per-run fields (not stored) ─────────────────────────────────────────────
const doc = ref<Doc>('world_state')
const partyConfigPath = ref('')
const planningConfigPath = ref('')
const namesText = ref('')
const maxTokens = ref<Num>('')
const dumpOnly = ref(false)
const forceBuild = ref(false)
// Per-run, never persisted: replacing a reviewed draft must be a deliberate act each time.
const forceSynth = ref(false)
// Per run, never persisted and unchecked on every load (spec 033 FR-018b): write a code-built Key NPCs line
// for an NPC with no published dossier instead of refusing. world_state and planning.
const fallbackNpcLines = ref(false)
// Extract (per run, never persisted): a blank chunk size uses grounding.yaml summary_native.extract.chunk_chars.
const extractChunkChars = ref<Num>('')
const extractMaxTokens = ref<Num>('')
const extractDumpOnly = ref(false)
const forceExtract = ref(false)
// Per run, never persisted (endpoints are machine wiring, not campaign state): one URL per line, all serving the
// same model; blank uses the single endpoint the backend resolves. Workers = in-flight calls per endpoint.
const extractEndpointsText = ref('')
const extractParallel = ref<Num>('')
// Audit (per run, never persisted): track files are prefilled from grounding.yaml campaign_state.track_files and
// editable here; the judge uses the extraction backend, so a blank model uses summary_native.extract.model.
const auditTrackText = ref('')
const auditCandidates = ref<Num>('')
const auditMaxTokens = ref<Num>('')
const auditDumpOnly = ref(false)
const forceAudit = ref(false)
const auditModel = ref('')
const auditEndpointsText = ref('')
const auditParallel = ref<Num>('')
// Prose step (every document): blank uses grounding.yaml summary_native.prose.
const proseModel = ref('')
const proseEffort = ref('')
const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'] as const

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

interface PlanningNoteSelector { id: string; path: string; record_ids?: string[] }
interface AuthorityNoteRecord {
  id: string; classification: string; audience: string[]; effective: Record<string, unknown>
  status: string; anchor: string; section_sha256: string
}
interface AuthorityNoteMember {
  selector_id?: string; path?: string; resolved_path?: string; external?: boolean
  record_ids?: string[]; reason?: string; sha256?: string
  records?: AuthorityNoteRecord[]
}
interface AuthorityNotePreview {
  audience?: string; members: AuthorityNoteMember[]; selection_sha256?: string; selection_digest?: string; membership_digest: string; warnings: string[]
}
const planningNoteSelectors = ref<PlanningNoteSelector[]>([])
const planningNoteId = ref('')
const planningNotePath = ref('')
const planningNoteRecordIds = ref('')
const planningNoteError = ref('')
const authorityAudience = ref('gm')
const authorityCharacterId = ref('')
const authorityAudienceTarget = computed(() => authorityAudience.value === 'character'
  ? `character:${authorityCharacterId.value.trim()}` : authorityAudience.value)
// Non-GM synthesis requires a successful, current audience-specific preview.
const audienceExecutionEnabled = ref(true)
const authorityNotePreview = ref<AuthorityNotePreview | null>(null)
const authorityPreviewKey = ref('')
const audiencePreviewApproved = computed(() => authorityAudienceTarget.value === 'gm' || (
  authorityNotePreview.value?.audience === authorityAudienceTarget.value
  && authorityPreviewKey.value === selectorKey()
  && authorityNotePreview.value.members.length > 0
))
const audienceCoverageRefusal = computed(() => authorityAudienceTarget.value !== 'gm' && (!audienceExecutionEnabled.value || !audiencePreviewApproved.value)
  ? (audienceExecutionEnabled.value
      ? 'Preview complete authorized support for this audience before planning synthesis.'
      : 'This audience has no enabled end-to-end coverage yet; planning synthesis remains unavailable.') : '')

function selectorKey(selectors = planningNoteSelectors.value) {
  return selectors.map(({ id, path, record_ids }) => `${id}=${path}#${(record_ids ?? []).join(',')}`).join('\n')
}

function clearPlanningPreview() {
  authorityNotePreview.value = null
  authorityPreviewKey.value = ''
}

async function refreshPlanningNoteSelectors() {
  planningNoteError.value = ''
  try {
    planningNoteSelectors.value = await apiFetch<PlanningNoteSelector[]>('/api/planning/notes')
    if (authorityPreviewKey.value !== selectorKey()) clearPlanningPreview()
  } catch (e) {
    planningNoteSelectors.value = []
    planningNoteError.value = e instanceof Error ? e.message : String(e)
  }
}

async function createPlanningNoteSelector() {
  planningNoteError.value = ''
  clearPlanningPreview()
  const record_ids = lines(planningNoteRecordIds.value)
  try {
    const response = await fetch('/api/planning/notes', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: planningNoteId.value.trim(), path: planningNotePath.value.trim(),
        ...(record_ids.length ? { record_ids } : {}) }),
    })
    if (!response.ok) throw new Error(await response.text())
    planningNoteId.value = ''; planningNotePath.value = ''; planningNoteRecordIds.value = ''
    await refreshPlanningNoteSelectors()
  } catch (e) {
    planningNoteError.value = e instanceof Error ? e.message : String(e)
  }
}

async function deletePlanningNoteSelector(selector: PlanningNoteSelector) {
  planningNoteError.value = ''
  clearPlanningPreview()
  try {
    const response = await fetch(`/api/planning/notes/${encodeURIComponent(selector.id)}`, { method: 'DELETE' })
    if (!response.ok) throw new Error(await response.text())
    await refreshPlanningNoteSelectors()
  } catch (e) {
    planningNoteError.value = e instanceof Error ? e.message : String(e)
  }
}

async function updatePlanningNoteSelector(selector: PlanningNoteSelector) {
  planningNoteError.value = ''
  clearPlanningPreview()
  try {
    const response = await fetch(`/api/planning/notes/${encodeURIComponent(selector.id)}`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(selector),
    })
    if (!response.ok) throw new Error(await response.text())
    await refreshPlanningNoteSelectors()
  } catch (e) {
    planningNoteError.value = e instanceof Error ? e.message : String(e)
  }
}

async function previewPlanningNotes() {
  planningNoteError.value = ''
  clearPlanningPreview()
  try {
    // Preview the saved planning configuration, never the browser's editable
    // table. This makes its digest bind the same selector set the CLI will run.
    await refreshPlanningNoteSelectors()
    const response = await fetch(`${BASE}/authority/notes/preview`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ audience: authorityAudienceTarget.value,
        ...(planningConfigPath.value.trim() ? { planning_config: planningConfigPath.value.trim() } : {}) }),
    })
    const body = await response.json() as AuthorityEnvelope<AuthorityNotePreview>
    if (!response.ok || !body.ok) throw new Error(body.message || `API ${response.status}`)
    authorityNotePreview.value = body.data
    authorityPreviewKey.value = selectorKey()
  } catch (e) {
    planningNoteError.value = e instanceof Error ? e.message : String(e)
  }
}

const reviewedAuthoritySelections = computed(() => {
  if (!authorityNotePreview.value || authorityPreviewKey.value !== selectorKey()) return []
  // The SHA is the reviewed immutable snapshot named by the current CLI.
  // Keep the legacy selector tuple fallback only for the pre-US3 response
  // shape used by older campaigns and route mocks.
  if (authorityNotePreview.value.selection_sha256) return [authorityNotePreview.value.selection_sha256]
  return planningNoteSelectors.value.map(selector => `${selector.id}=${selector.path}`)
})

const reviewedSelectionDigest = computed(() => authorityNotePreview.value?.selection_sha256 ?? authorityNotePreview.value?.selection_digest ?? '')

function memberClassification(member: AuthorityNoteMember) {
  return [...new Set((member.records ?? []).map(record => record.classification))].join(', ') || 'withheld'
}

function memberAudience(member: AuthorityNoteMember) {
  return [...new Set((member.records ?? []).flatMap(record => record.audience))].join(', ') || 'withheld'
}

function memberRecordScope(member: AuthorityNoteMember) {
  if (member.records?.length) return member.records.map(record => record.id).join(', ')
  return member.record_ids?.join(', ') || 'withheld'
}

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
  return runAuthority(`records/${encodeURIComponent(recordId)}/propose`, { summaries_dir: summariesDir.value })
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
const num = (n: Num) => (typeof n === 'number' ? n : undefined)

// ── Chapters / range picker ─────────────────────────────────────────────────
interface Chapters {
  present: number[]
  files: { chapter: number; path: string }[]
  duplicate_chapters: number[]
}
const chapters = ref<Chapters | null>(null)
const chaptersError = ref('')
let chaptersTimer: ReturnType<typeof setTimeout> | null = null

async function loadChapters() {
  chaptersError.value = ''
  chapters.value = null
  const dir = summariesDir.value.trim()
  if (!dir) return
  try {
    chapters.value = await apiFetch<Chapters>(
      `${BASE}/chapters?summaries_dir=${encodeURIComponent(dir)}`,
    )
  } catch (e) {
    chaptersError.value = e instanceof Error ? e.message : String(e)
  }
}

watch(summariesDir, () => {
  if (chaptersTimer) clearTimeout(chaptersTimer)
  chaptersTimer = setTimeout(loadChapters, 400)
})

// "All chapters" is a deliberate choice: it writes the first and last chapter
// into the range explicitly, so the run (and the stored config) names them.
function selectAll() {
  const present = chapters.value?.present ?? []
  if (!present.length) return
  rangeSince.value = present[0]
  rangeUntil.value = present[present.length - 1]
}

const rangeChosen = computed(
  () => typeof rangeSince.value === 'number' && typeof rangeUntil.value === 'number',
)
const rangeInverted = computed(
  () => rangeChosen.value && (rangeSince.value as number) > (rangeUntil.value as number),
)
const ready = computed(() => !!summariesDir.value.trim() && rangeChosen.value && !rangeInverted.value)

// ── Run params ──────────────────────────────────────────────────────────────
const baseParams = computed(() => ({
  summaries_dir: summariesDir.value.trim(),
  since: num(rangeSince.value),
  until: num(rangeUntil.value),
}))
const validateParams = computed(() => ({
  ...baseParams.value, dup_threshold: num(dupThreshold.value),
}))
const buildParams = computed(() => ({
  ...baseParams.value, dup_threshold: num(dupThreshold.value), force: forceBuild.value,
}))
const usesKeyNpcs = computed(() => KEY_NPC_DOCS.includes(doc.value))
const extractParams = computed(() => ({
  ...baseParams.value,
  chunk_chars: num(extractChunkChars.value),
  max_tokens: num(extractMaxTokens.value),
  dump_only: extractDumpOnly.value,
  force: forceExtract.value,
  endpoints: lines(extractEndpointsText.value),
  parallel: num(extractParallel.value),
}))
const auditParams = computed(() => ({
  ...baseParams.value,
  track_file: lines(auditTrackText.value),
  candidates: num(auditCandidates.value),
  max_tokens: num(auditMaxTokens.value),
  dump_only: auditDumpOnly.value,
  force: forceAudit.value,
  model: auditModel.value.trim() || undefined,
  endpoints: lines(auditEndpointsText.value),
  parallel: num(auditParallel.value),
}))
// The prose step takes its backend and model from grounding.yaml summary_native.prose, so the page does not send
// the app-wide model for any document.
const synthParams = computed(() => ({
  ...baseParams.value,
  // The NPC selection of world_state's Key NPCs and planning's NPC Dossiers (campaign_state has no such section and
  // party selects no NPCs: the server refuses these for them).
  ...(usesKeyNpcs.value
    ? {
        name: lines(namesText.value),
        recent_chapters: num(recentChapters.value),
        recurring_min: num(recurringMin.value),
        fallback_npc_lines: fallbackNpcLines.value,
      }
    : {}),
  ...(doc.value === 'party' ? { party_config: partyConfigPath.value.trim() } : {}),
  ...(doc.value === 'planning' ? { planning_config: planningConfigPath.value.trim() } : {}),
  ...(doc.value === 'planning' && reviewedAuthoritySelections.value.length
    ? { authority_selection: reviewedAuthoritySelections.value, audience: authorityAudienceTarget.value }
    : {}),
  max_tokens: num(maxTokens.value),
  dump_only: dumpOnly.value,
  force: forceSynth.value,
  model: proseModel.value.trim() || undefined,
  claude_code_effort: proseEffort.value || undefined,
}))

// ── Report and drafts ───────────────────────────────────────────────────────
interface Finding {
  file: string; line: number | null; code: string; message: string
  expected: string | null; found: string | null; blocking: boolean; in_range: boolean
}
interface Report {
  range: { since: number; until: number; present: number[]; gaps: number[] }
  files_scanned: number; files_in_range: number
  blocking_count: number; files_failing: number; non_blocking_count: number
  findings: Finding[]
  existing_corpus?: { state: string; [k: string]: unknown }
}
interface DraftRow { doc: string; path: string; status: 'draft' | 'incomplete' | 'report'; bytes: number }
interface ExtractChunk { index: number; chapters: string; status: string; kept: number; dropped: number; outlier: boolean }
// The ratified-thread counts of the last build that read the thread registry (read by the server from state/threads/attach.json).
interface ThreadCounts {
  present: boolean; ratified_in_range: number | null; open: number | null; dormant: number | null
  unattached: number | null; ambiguous: number | null; pending_groups: number | null
}
interface ExtractState {
  present: boolean; complete: boolean; stale: boolean; stale_reason: string | null
  backend?: string; model?: string; chunk_chars?: number; absent_chapters?: number[]
  chunks: ExtractChunk[]
  totals: { chunks: number; checked: number; kept: number; dropped: number }
  outliers: string[]; drops_file: string | null
}

const report = ref<Report | null>(null)
const reportNote = ref('')
const drafts = ref<DraftRow[]>([])
const draftsNote = ref('')
interface AuditCounts {
  items: number; supported: number; not_found: number; no_candidates: number
  not_shown: number; unverified: number; not_judged: number
}
interface AuditState {
  present: boolean; complete: boolean; stale: boolean; stale_reason: string | null
  counts: AuditCounts | null; summary?: string; backend?: string | null; model?: string | null
  candidates?: number | null; audit_file: string | null; track_files: string[]
}
const extractState = ref<ExtractState | null>(null)
const auditState = ref<AuditState | null>(null)
// Each document's last build: words written against each prose section's budget (null before a build).
interface BudgetRow { budget: number; words: number; over: boolean }
const budgets = ref<Record<string, Record<string, BudgetRow> | null>>({})
const threadCounts = ref<ThreadCounts | null>(null)
// Each chunked document's last annotate step (written by synth, and again by Annotate).
interface AnnotationCounts { later: number; since: number; unverified: number; removed: number; lines: number }
const annotations = ref<Record<string, AnnotationCounts>>({})
const docAnnotations = computed(() => annotations.value[doc.value] ?? null)
const budgetRows = computed(() => Object.entries(budgets.value[doc.value] ?? {}))
const overBudget = computed(() => budgetRows.value.filter(([, r]) => r.over).length)

const duplicates = computed(() => report.value?.findings.filter(f => f.code === 'possible-duplicate') ?? [])
const otherFindings = computed(() => report.value?.findings.filter(f => f.code !== 'possible-duplicate') ?? [])

async function refreshOutputs() {
  report.value = null; reportNote.value = ''
  drafts.value = []; draftsNote.value = ''
  extractState.value = null
  auditState.value = null
  budgets.value = {}
  threadCounts.value = null
  annotations.value = {}
  if (!rangeChosen.value) return
  const q = `since=${rangeSince.value}&until=${rangeUntil.value}`
  try {
    const state = await apiFetch<{
      extract: ExtractState; audit: AuditState; budgets: Record<string, Record<string, BudgetRow> | null>
      annotations: Record<string, AnnotationCounts>
      missing_dossiers: MissingNpc[] | null; missing_dossiers_refused: boolean
      planning_missing_dossiers: MissingNpc[] | null; planning_missing_dossiers_refused: boolean
      threads: ThreadCounts
    }>(`${BASE}/state?${q}`)
    extractState.value = state.extract
    auditState.value = state.audit
    // Prefill the track files from the configured list, once; after that the box is the GM's.
    if (!auditTrackText.value.trim() && state.audit?.track_files?.length) {
      auditTrackText.value = state.audit.track_files.join('\n')
    }
    budgets.value = state.budgets ?? {}
    annotations.value = state.annotations ?? {}
    // The latest attempt's list for each document, so a refusal is still shown after a reload.
    missingByDoc.value = {
      world_state: state.missing_dossiers_refused ? (state.missing_dossiers ?? []) : [],
      planning: state.planning_missing_dossiers_refused ? (state.planning_missing_dossiers ?? []) : [],
    }
    threadCounts.value = state.threads ?? null
  } catch {
    extractState.value = null // the Extract panel simply stays empty; the other outputs still load
  }
  try {
    report.value = await apiFetch<Report>(`${BASE}/report?${q}`)
  } catch (e) {
    reportNote.value = e instanceof Error && e.message.startsWith('API 404')
      ? 'No validation report for this range yet. Run Validate.'
      : (e instanceof Error ? e.message : String(e))
  }
  try {
    drafts.value = await apiFetch<DraftRow[]>(`${BASE}/drafts?${q}`)
    if (!drafts.value.length) draftsNote.value = 'No drafts for this range yet.'
  } catch (e) {
    draftsNote.value = e instanceof Error && e.message.startsWith('API 404')
      ? 'Nothing built for this range yet. Run Build.'
      : (e instanceof Error ? e.message : String(e))
  }
}

// The NPCs a refused build named, parsed from the CLI's own message (one `  Name: state` line each).
interface MissingNpc { name: string; state: string }
const missingByDoc = ref<Record<string, MissingNpc[]>>({})
const missingNpcs = computed(() => missingByDoc.value[doc.value] ?? [])
const MISSING_HEADER = /need a published, verified dossier/
const MISSING_LINE = /^ {2}(?!summary_native )(.+?): (not drafted|drafted, not verified|drafted, not published|failed verification.*|published for .+)$/
function parseMissingNpcs(output: string): MissingNpc[] {
  if (!MISSING_HEADER.test(output)) return []
  const out: MissingNpc[] = []
  for (const raw of output.split('\n')) {
    const m = MISSING_LINE.exec(raw.trimEnd())
    if (m) out.push({ name: m[1], state: m[2] })
  }
  return out
}

function onSynthDone(rc: number, output = '') {
  forceSynth.value = false
  if (usesKeyNpcs.value) missingByDoc.value = { ...missingByDoc.value, [doc.value]: rc === 2 ? parseMissingNpcs(output) : [] }
  refreshOutputs()
}

watch(doc, () => { fallbackNpcLines.value = false })

const annotateDryParams = computed(() => ({ ...baseParams.value, dry_run: true }))
function onAnnotateDone() { refreshOutputs() }

function onAuditDone() {
  forceAudit.value = false
  refreshOutputs()
}

function onExtractDone() {
  forceExtract.value = false
  refreshOutputs()
}

watch([rangeSince, rangeUntil], refreshOutputs)

onMounted(async () => {
  // useGroundingRun hydrates the refs on mount; give it a tick before reading.
  await (config.groundingConfig ?? config.refreshGrounding())
  setTimeout(() => { loadChapters(); refreshOutputs(); refreshAuthority(); refreshPlanningNoteSelectors() }, 50)
})
</script>

<template>
  <ReviewLauncher context="grounding" />
  <div class="page">
    <div class="page-header">
      <h2>Summary-native</h2>
      <p class="subtitle">
        Build grounding-document drafts directly from reviewed session summaries &mdash; no extraction pass.
        Drafts are written for review; nothing here promotes one to the live document.
      </p>
    </div>

    <div class="form-grid">
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

          <div v-if="authoritySelectedId" class="field authority-withdraw">
            <label class="field-label">Withdrawal reason for {{ authoritySelectedId }}</label>
            <input class="field-input" v-model="authorityReason" placeholder="Reason for requesting a safe reversal" />
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
            <label class="field-label">Applied resolution ruling file</label>
            <input class="field-input" v-model="authorityResolutionRecordFile" placeholder="docs/authority/records/gate-resolution.yaml" />
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

      <!-- Input -->
      <div class="form-section">
        <PathField v-model="summariesDir" label="Summaries directory" required resolve-base="campaign"
          help="A directory of structured session summaries (*.md) whose filenames start with the chapter number." />
        <span v-if="chaptersError" class="field-error">{{ chaptersError }}</span>
      </div>

      <!-- Range -->
      <div class="form-section">
        <label class="field-label">Chapter range</label>
        <div v-if="chapters && chapters.present.length" class="range-row">
          <select class="field-input narrow" v-model="rangeSince" aria-label="First chapter">
            <option :value="null" disabled>first&hellip;</option>
            <option v-for="c in chapters.present" :key="c" :value="c">{{ c }}</option>
          </select>
          <span class="range-sep">to</span>
          <select class="field-input narrow" v-model="rangeUntil" aria-label="Last chapter">
            <option :value="null" disabled>last&hellip;</option>
            <option v-for="c in chapters.present" :key="c" :value="c">{{ c }}</option>
          </select>
          <button class="btn-neutral btn-sm" @click="selectAll">All chapters</button>
        </div>
        <span v-else class="field-help">
          {{ summariesDir.trim() ? 'No numbered summaries found in that directory.' : 'Set the summaries directory to list its chapters.' }}
        </span>
        <span v-if="chapters && chapters.duplicate_chapters.length" class="field-error">
          More than one file for chapter {{ chapters.duplicate_chapters.join(', ') }} &mdash; Validate will block until one is removed.
        </span>
        <span v-if="rangeInverted" class="field-error">The first chapter is after the last.</span>
        <span v-else-if="!rangeChosen" class="field-help">
          Choose a range explicitly. &ldquo;All chapters&rdquo; fills in the first and last chapter for you.
        </span>
      </div>

      <!-- 1. Validate -->
      <div class="form-section">
        <h3 class="step">1. Validate</h3>
        <div class="field">
          <label class="field-label">Possible-duplicate threshold</label>
          <input type="number" step="0.01" min="0" max="1" class="field-input narrow" v-model.number="dupThreshold" />
          <span class="field-help">Similarity ratio above which two entries are reported as possible duplicates. Blank uses the stored default.</span>
        </div>
        <RunPanel :endpoint="`${BASE}/run/validate`" :params="validateParams" :disabled="!ready"
          label="Validate" @done="refreshOutputs" />
      </div>

      <!-- 2. Build -->
      <div class="form-section">
        <h3 class="step">2. Build corpus</h3>
        <label class="checkbox-label">
          <input type="checkbox" v-model="forceBuild" /> Rebuild existing corpus (--force)
        </label>
        <RunPanel :endpoint="`${BASE}/run/build`" :params="buildParams" :disabled="!ready"
          label="Build" @done="refreshOutputs" />
      </div>

      <!-- 3. Extract -->
      <div class="form-section">
        <h3 class="step">3. Extract notes</h3>
        <span class="field-help">
          Reads the full summaries a few chapters at a time and writes notes, which code then checks:
          every citation must resolve inside its chunk, every quotation must be verbatim, every note must carry its tag.
          Every document (world_state, campaign_state, party and planning) is built from these notes. Notes that fail are dropped and listed in drops.md.
        </span>
        <div class="num-grid">
          <div class="field">
            <label class="field-label">Chunk size (characters)</label>
            <input type="number" min="1" class="field-input" v-model.number="extractChunkChars" />
            <span class="field-help">Whole chapters per call, up to this size. Blank uses the stored default.</span>
          </div>
          <div class="field">
            <label class="field-label">Max tokens</label>
            <input type="number" min="1" class="field-input" v-model.number="extractMaxTokens" />
            <span class="field-help">Per call. Blank uses the CLI default.</span>
          </div>
          <div class="field">
            <label class="field-label">Workers per endpoint</label>
            <input type="number" min="1" class="field-input" v-model.number="extractParallel" />
            <span class="field-help">Calls in flight at once on each endpoint (<code>--parallel</code>). Blank = 6.</span>
          </div>
        </div>
        <div class="field">
          <label class="field-label">Endpoints</label>
          <textarea class="field-textarea" v-model="extractEndpointsText" rows="2"
            placeholder="One URL per line, e.g. http://spark:8001/v1 &mdash; blank uses the single configured endpoint" />
          <span class="field-help">
            Several endpoints share one queue of chunks, so a slower box takes fewer (<code>--endpoints</code>, dgx backend only).
            Each is checked before any call: it must answer and serve the model. Not saved.
          </span>
        </div>
        <label class="checkbox-label">
          <input type="checkbox" v-model="extractDumpOnly" /> Dump only &mdash; write the prompts and the manifest, make no model call
        </label>
        <label class="checkbox-label">
          <input type="checkbox" v-model="forceExtract" /> Re-extract every chunk (--force)
        </label>
        <RunPanel :endpoint="`${BASE}/run/extract`" :params="extractParams" :disabled="!ready"
          label="Extract notes" @done="onExtractDone" />
        <div v-if="extractState && extractState.present" class="panel extract-state">
          <div class="counts">
            <span :class="extractState.complete ? 'ok' : 'bad'">
              {{ extractState.complete ? 'complete' : 'incomplete' }}
              ({{ extractState.totals.checked }} of {{ extractState.totals.chunks }} chunks checked)
            </span>
            <span>{{ extractState.totals.kept }} notes kept</span>
            <span>{{ extractState.totals.dropped }} dropped</span>
            <span v-if="extractState.model">{{ extractState.backend }} / {{ extractState.model }}</span>
            <span v-if="extractState.absent_chapters?.length">absent chapters: {{ extractState.absent_chapters.join(', ') }}</span>
          </div>
          <p v-if="extractState.stale" class="field-error">
            The notes are stale: {{ extractState.stale_reason }}
          </p>
          <p v-if="!extractState.complete" class="field-error">
            Some chunks have no checked notes. Run Extract again: only the missing chunks are extracted.
          </p>
          <table class="drafts chunks">
            <thead><tr><th>Chunk</th><th>Chapters</th><th>Status</th><th>Kept</th><th>Dropped</th><th></th></tr></thead>
            <tbody>
              <tr v-for="c in extractState.chunks" :key="c.index" :class="{ outlier: c.outlier }">
                <td>{{ c.index }}</td>
                <td>{{ c.chapters }}</td>
                <td :class="c.status === 'checked' ? 'ok' : 'bad'">{{ c.status }}</td>
                <td>{{ c.kept }}</td>
                <td>{{ c.dropped }}</td>
                <td><span v-if="c.outlier" class="bad">outlier: possible runaway call</span></td>
              </tr>
            </tbody>
          </table>
          <span v-if="extractState.drops_file" class="field-help">
            Every dropped note and its reason: <code>{{ extractState.drops_file }}</code>
          </span>
        </div>
      </div>

      <!-- 4. Audit -->
      <div class="form-section">
        <h3 class="step">4. Audit the tracking files</h3>
        <span class="field-help">
          campaign_state's &ldquo;Audit: Tracking Claims&rdquo;, as its own step. For each <code>- </code> line of the tracking files,
          code picks up to N candidate chapters by the item's names, a model judges that one item against only those chapters,
          and code accepts SUPPORTED only when the answer cites a candidate chapter and quotes a span that is verbatim there.
          Anything else is NOT FOUND (and says why). Verdicts are cached per item, so re-running judges only what changed.
          Needs no extracted notes; run it before Synthesize campaign_state, which renders its Audit section from the result.
        </span>
        <div class="field">
          <label class="field-label">Track files</label>
          <textarea class="field-textarea" v-model="auditTrackText" rows="3"
            placeholder="One path per line &mdash; blank uses grounding.yaml campaign_state.track_files" />
          <span class="field-help">
            Prefilled from the Campaign State page's list; edit for this run only. Synthesize compares the audit with the
            configured list, so an audit of other files reads as stale there.
          </span>
        </div>
        <div class="num-grid">
          <div class="field">
            <label class="field-label">Candidate chapters per item</label>
            <input type="number" min="1" class="field-input" v-model.number="auditCandidates" />
            <span class="field-help">At most this many chapters are shown to the judge. Blank uses the CLI default.</span>
          </div>
          <div class="field">
            <label class="field-label">Max tokens</label>
            <input type="number" min="1" class="field-input" v-model.number="auditMaxTokens" />
            <span class="field-help">Per call. Blank uses the CLI default.</span>
          </div>
          <div class="field">
            <label class="field-label">Workers per endpoint</label>
            <input type="number" min="1" class="field-input" v-model.number="auditParallel" />
            <span class="field-help">Calls in flight at once on each endpoint (<code>--parallel</code>). Blank = 6.</span>
          </div>
        </div>
        <div class="field">
          <label class="field-label">Model</label>
          <input class="field-input" v-model="auditModel" placeholder="blank uses summary_native.extract.model" />
          <span class="field-help">The judge runs on the extraction backend.</span>
        </div>
        <div class="field">
          <label class="field-label">Endpoints</label>
          <textarea class="field-textarea" v-model="auditEndpointsText" rows="2"
            placeholder="One URL per line &mdash; blank uses the single configured endpoint" />
          <span class="field-help">
            Several endpoints share one queue of items (<code>--endpoints</code>, dgx backend only); each is checked before any call. Not saved.
          </span>
        </div>
        <label class="checkbox-label">
          <input type="checkbox" v-model="auditDumpOnly" /> Dump only &mdash; write the prompts, make no model call
        </label>
        <label class="checkbox-label">
          <input type="checkbox" v-model="forceAudit" /> Re-judge every item (--force)
        </label>
        <RunPanel :endpoint="`${BASE}/run/audit`" :params="auditParams" :disabled="!ready"
          label="Run audit" @done="onAuditDone" />
        <div v-if="auditState && auditState.present && auditState.counts" class="panel audit-state">
          <div class="counts">
            <span :class="auditState.complete ? 'ok' : 'bad'">{{ auditState.complete ? 'complete' : 'incomplete' }}</span>
            <span>{{ auditState.counts.items }} items</span>
            <span class="ok">{{ auditState.counts.supported }} supported</span>
            <span>{{ auditState.counts.not_found }} not found</span>
            <span>({{ auditState.counts.no_candidates }} no candidate chapters,
              {{ auditState.counts.not_shown }} not shown,
              <span :class="auditState.counts.unverified ? 'bad' : ''">{{ auditState.counts.unverified }} unverified</span>)</span>
            <span v-if="auditState.counts.not_judged" class="bad">{{ auditState.counts.not_judged }} not judged</span>
            <span v-if="auditState.model">{{ auditState.backend }} / {{ auditState.model }}</span>
          </div>
          <p v-if="auditState.stale" class="field-error">The audit is stale: {{ auditState.stale_reason }}</p>
          <p v-if="!auditState.complete" class="field-error">
            Some items have no verdict (their call failed). Run the audit again: only those are judged.
          </p>
          <span v-if="auditState.audit_file" class="field-help">
            Every verdict, with its citation and span or the reason it was not accepted: <code>{{ auditState.audit_file }}</code>
          </span>
        </div>
      </div>

      <!-- 5. Synth -->
      <div class="form-section">
        <h3 class="step">5. Synthesize a draft</h3>
        <div class="field">
          <label class="field-label">Document</label>
          <select class="field-input narrow" v-model="doc">
            <option v-for="d in DOCS" :key="d" :value="d">{{ d }}</option>
          </select>
        </div>
        <span class="field-help">
          Built from the checked notes: run Extract first. Code builds the timeline, completed list, NPC status table and
          every pointer; the model writes each remaining section from the notes routed to it. The tracking audit is its own step.
          <template v-if="doc === 'party'">
            One call per character, then the overview and the dynamics. Code writes each character&rsquo;s heading and level line;
            a character with no notes says so and makes no call. The sheet and backstory come from the party config.
          </template>
          <template v-if="doc === 'world_state'">
            Key NPCs are rendered from the published NPC dossiers: the build refuses when a selected NPC has none.
          </template>
          <template v-if="doc === 'campaign_state'">
            Resolved Plot Threads and Active Quests &amp; Open Threads are built from the threads the GM has ratified
            (<RouterLink to="/grounding/threads">Threads page</RouterLink>): code decides which threads are closed or open, in
            what order, and lists the dormant and unratified ones; the model writes one entry per thread from that thread&rsquo;s own notes.
            Until threads are ratified these sections say so and point to the unratified notes.
          </template>
          <template v-if="doc === 'planning'">
            Code builds the Threat Tracker, picks the NPCs and factions, orders Active Plots by the ratified threads and lists the
            unratified thread notes verbatim. NPC Dossiers are rendered from the published NPC dossiers: the build refuses when a
            selected NPC has none.
          </template>
        </span>
        <PathField v-if="doc === 'party'" v-model="partyConfigPath" label="Party config" resolve-base="campaign"
          help="The party roster (sheets and backstories). Blank uses config/party.yaml." />
        <PathField v-if="doc === 'planning'" v-model="planningConfigPath" label="Planning config" resolve-base="campaign"
          help="Tracked NPCs, factions and arc scores. Blank uses config/planning.yaml; none means no arc scores." />
        <div v-if="doc === 'planning'" class="panel planning-notes">
          <div class="counts">
            <span>Authority note selectors</span>
            <button class="btn-neutral btn-sm" @click="refreshPlanningNoteSelectors">Refresh</button>
          </div>
          <table v-if="planningNoteSelectors.length" class="drafts">
            <thead><tr><th>Selector</th><th>Path</th><th>Record scope</th><th></th></tr></thead>
            <tbody>
              <tr v-for="selector in planningNoteSelectors" :key="selector.id">
                <td><code>{{ selector.id }}</code></td><td><input class="field-input" v-model="selector.path" @input="clearPlanningPreview" :aria-label="`Path for ${selector.id}`" /></td>
                <td>{{ selector.record_ids?.join(', ') || 'all matching records' }}</td>
                <td><button class="btn-neutral btn-sm" @click="updatePlanningNoteSelector(selector)">Save</button><button class="btn-neutral btn-sm" @click="deletePlanningNoteSelector(selector)">Remove</button></td>
              </tr>
            </tbody>
          </table>
          <div class="num-grid">
            <div class="field"><label class="field-label">Selector id</label><input class="field-input" v-model="planningNoteId" placeholder="gm-notes" /></div>
            <div class="field"><label class="field-label">Path or scoped glob</label><input class="field-input" v-model="planningNotePath" placeholder="notes/gm/*.md" /></div>
            <div class="field"><label class="field-label">Record ids, one per line (optional)</label><textarea class="field-textarea" v-model="planningNoteRecordIds" rows="2" /></div>
          </div>
          <button class="btn-neutral btn-sm" :disabled="!planningNoteId.trim() || !planningNotePath.trim()" @click="createPlanningNoteSelector">Add selector</button>
          <span v-if="planningNoteError" class="field-error">{{ planningNoteError }}</span>
          <div class="field authority-selection" data-test="authority-note-selection">
            <label class="field-label">Audience</label>
            <select class="field-input narrow" v-model="authorityAudience" @change="clearPlanningPreview">
              <option value="gm">GM</option><option value="players">Players</option><option value="characters">All characters</option><option value="character">Named character</option>
            </select>
            <input v-if="authorityAudience === 'character'" class="field-input" v-model="authorityCharacterId" @input="clearPlanningPreview" placeholder="Stable character id" aria-label="Stable character id" />
            <button class="btn-neutral btn-sm" :disabled="!planningNoteSelectors.length || (authorityAudience === 'character' && !authorityCharacterId.trim())" @click="previewPlanningNotes">Preview configured note selection</button>
            <span class="field-help">A configured note selection is forwarded to planning only after its concrete preview has been reviewed.</span>
            <span v-if="audienceCoverageRefusal" class="field-error">{{ audienceCoverageRefusal }}</span>
          </div>
          <div v-if="authorityNotePreview" class="panel authority-selection-preview" data-test="authority-note-preview">
            <div class="counts">
              <span>{{ authorityNotePreview.members.length }} resolved note(s)</span>
              <span>selection digest <code>{{ reviewedSelectionDigest }}</code></span>
              <span>membership digest <code>{{ authorityNotePreview.membership_digest }}</code></span>
            </div>
            <label class="field-label">Reviewed selection digest</label>
            <input class="field-input" :value="reviewedSelectionDigest" readonly aria-label="Reviewed selection digest" />
            <table v-if="authorityNotePreview.members.length" class="drafts authority-note-members">
              <thead><tr><th>Selector</th><th>Resolved note</th><th>Record scope</th><th>Classification</th><th>Audience</th><th>Reason</th><th>Digest</th></tr></thead>
              <tbody>
                <tr v-for="member in authorityNotePreview.members" :key="`${member.selector_id ?? 'restricted'}:${member.resolved_path ?? member.sha256 ?? member.reason}`">
                  <td><code>{{ member.selector_id ?? 'restricted' }}</code></td>
                  <td><code>{{ member.resolved_path ?? member.path ?? 'restricted member' }}</code><span v-if="member.external" class="bad"> external</span></td>
                  <td><code>{{ memberRecordScope(member) }}</code></td>
                  <td>{{ memberClassification(member) }}</td>
                  <td>{{ memberAudience(member) }}</td>
                  <td>{{ member.reason ?? 'authorized selection' }}</td>
                  <td><code>{{ member.sha256 ?? 'withheld' }}</code></td>
                </tr>
              </tbody>
            </table>
            <ul v-if="authorityNotePreview.warnings.length" class="field-error authority-selection-warnings">
              <li v-for="warning in authorityNotePreview.warnings" :key="warning">{{ warning }}</li>
            </ul>
          </div>
        </div>
        <div v-if="usesKeyNpcs" class="field">
          <label class="field-label">Named subjects</label>
          <textarea class="field-textarea" v-model="namesText" rows="2"
            placeholder="One subject per line &mdash; force-includes these dossiers" />
          <span class="field-help">
            Force-includes these global NPCs in {{ doc === 'planning' ? 'NPC Dossiers (the NPCs in planning.yaml are always included)' : 'Key NPCs' }}.
          </span>
        </div>
        <div class="num-grid">
          <div v-if="usesKeyNpcs" class="field">
            <label class="field-label">Recent chapters</label>
            <input type="number" min="0" class="field-input" v-model.number="recentChapters" />
            <span class="field-help">Counted back from the range end; 0 = all.<template v-if="usesKeyNpcs"> Picks the {{ doc === 'planning' ? 'NPC Dossiers' : 'Key NPCs' }}.</template></span>
          </div>
          <div v-if="usesKeyNpcs" class="field">
            <label class="field-label">Recurring minimum</label>
            <input type="number" min="0" class="field-input" v-model.number="recurringMin" />
            <span class="field-help">Observations that make an entity recurring.</span>
          </div>
          <div class="field">
            <label class="field-label">Max tokens</label>
            <input type="number" min="1" class="field-input" v-model.number="maxTokens" />
            <span class="field-help">Per call. Blank uses the CLI default.</span>
          </div>
        </div>
        <div class="num-grid">
          <div class="field">
            <label class="field-label">Prose model</label>
            <input type="text" class="field-input" v-model="proseModel" />
            <span class="field-help">Blank uses <code>summary_native.prose.model</code> from grounding.yaml.</span>
          </div>
          <div class="field">
            <label class="field-label">Effort (claude-code)</label>
            <select class="field-input narrow" v-model="proseEffort" aria-label="Prose effort">
              <option value="">stored default</option>
              <option v-for="e in EFFORTS" :key="e" :value="e">{{ e }}</option>
            </select>
            <span class="field-help">Applies only when the prose backend is claude-code.</span>
          </div>
        </div>
        <label class="checkbox-label">
          <input type="checkbox" v-model="dumpOnly" /> Dump only &mdash; write the prompts and run record, make no model call
        </label>
        <label class="checkbox-label">
          <input type="checkbox" v-model="forceSynth" /> Replace existing reviewed draft (--force)
        </label>
        <label v-if="usesKeyNpcs" class="checkbox-label">
          <input type="checkbox" v-model="fallbackNpcLines" /> Write fallback lines for NPCs without a published dossier
        </label>
        <span v-if="usesKeyNpcs && fallbackNpcLines" class="field-help">
          This run only. Each such NPC gets a line built by code from its checked notes and marked
          &ldquo;(no published dossier &mdash; from checked notes)&rdquo;. Not saved.
        </span>
        <RunPanel :endpoint="`${SYNTH_ENDPOINT}/${doc}`" :params="synthParams" :disabled="!ready || (doc === 'planning' && !!audienceCoverageRefusal)"
          :label="`Synthesize ${doc}`" @done="onSynthDone" />
        <div v-if="usesKeyNpcs && missingNpcs.length" class="panel missing-npcs">
          <div class="counts">
            <span class="bad">Build refused: {{ missingNpcs.length }} selected NPC(s) have no published, verified dossier</span>
          </div>
          <table class="drafts">
            <thead><tr><th>NPC</th><th>Dossier state</th></tr></thead>
            <tbody>
              <tr v-for="n in missingNpcs" :key="n.name">
                <td>{{ n.name }}</td>
                <td class="bad">{{ n.state }}</td>
              </tr>
            </tbody>
          </table>
          <span class="field-help">
            Draft, verify and publish them on the <RouterLink to="/npcs/dossiers">NPC dossiers page</RouterLink>,
            then build again &mdash; or tick &ldquo;Write fallback lines&rdquo; above for this run.
          </span>
        </div>
        <div v-if="doc === 'planning'" class="panel threads">
          <div class="counts">
            <span>Ratified threads (last build that read the thread registry)</span>
            <template v-if="threadCounts?.present">
              <span data-test="thread-in-range">{{ threadCounts.ratified_in_range }} with notes in range</span>
              <span data-test="thread-open">{{ threadCounts.open }} open</span>
              <span data-test="thread-dormant">{{ threadCounts.dormant }} dormant</span>
              <span data-test="thread-unattached" :class="threadCounts.unattached ? 'bad' : 'ok'">{{ threadCounts.unattached }} unratified notes</span>
              <span v-if="threadCounts.ambiguous" class="bad" data-test="thread-ambiguous">{{ threadCounts.ambiguous }} ambiguous name(s)</span>
            </template>
            <span v-else>not built yet</span>
            <span v-if="threadCounts?.pending_groups" data-test="thread-pending">{{ threadCounts.pending_groups }} proposal group(s) awaiting a ruling</span>
          </div>
          <span class="field-help">
            Active Plots lists only the threads the GM has ratified; the other thread notes are listed verbatim under
            &ldquo;Unratified thread notes&rdquo;. Propose groupings and rule on them on the
            <RouterLink to="/grounding/threads">Threads page</RouterLink>, then build again.
          </span>
        </div>
        <div v-if="budgetRows.length" class="panel budgets">
          <div class="counts">
            <span>Word budgets (last {{ doc }} build; citations not counted)</span>
            <span :class="overBudget ? 'bad' : 'ok'">
              {{ overBudget ? `${overBudget} over budget` : 'all within budget' }}
            </span>
          </div>
          <table class="drafts">
            <thead><tr><th>Section</th><th>Words</th><th>Budget</th><th></th></tr></thead>
            <tbody>
              <tr v-for="[name, r] in budgetRows" :key="name">
                <td>{{ name }}</td>
                <td>{{ r.words }}</td>
                <td>{{ r.budget }}</td>
                <td :class="r.over ? 'bad' : 'ok'">{{ r.over ? 'OVER (kept whole, not truncated)' : 'ok' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 6. Annotate -->
      <div class="form-section">
        <h3 class="step">6. Annotate the {{ doc }} draft</h3>
        <span class="field-help">
          Deterministic: no model is called and no line is reworded. Where a newer checked note, a mentioned NPC's later status,
          another section, a non-verbatim quotation or an unresolved citation bears on a line, the evidence is appended under it
          (<code>&#9888; later:</code>, <code>&#8505; since:</code>, <code>&#9888; unverified:</code>); a player character listed as a
          companion is removed. Synthesize already does this; run it again after publishing a dossier or editing a summary.
          Key NPCs, planning&rsquo;s NPC Dossiers and Threat Tracker, the dormant and unratified thread blocks and the other
          code-built sections are never annotated.
        </span>
        <div v-if="docAnnotations" class="panel annotations">
          <div class="counts">
            <span>Last annotate step:</span>
            <span>{{ docAnnotations.later }} later</span>
            <span>{{ docAnnotations.since }} since</span>
            <span :class="docAnnotations.unverified ? 'bad' : ''">{{ docAnnotations.unverified }} unverified</span>
            <span>{{ docAnnotations.removed }} removed</span>
            <span>on {{ docAnnotations.lines }} lines</span>
          </div>
          <span class="field-help">Every hit: <code>annotations.md</code> (listed under Drafts).</span>
        </div>
        <RunPanel :endpoint="`${BASE}/run/annotate/${doc}`" :params="annotateDryParams" :disabled="!ready"
          :label="`Preview annotations for ${doc} (dry run)`" />
        <RunPanel :endpoint="`${BASE}/run/annotate/${doc}`" :params="baseParams" :disabled="!ready"
          :label="`Annotate ${doc}`" @done="onAnnotateDone" />
      </div>

      <!-- 7. Compare -->
      <div class="form-section">
        <h3 class="step">7. Compare with the live document</h3>
        <span class="field-help">Diffs the {{ doc }} draft against docs/{{ doc }}.md. Read-only.</span>
        <RunPanel :endpoint="`${BASE}/run/compare/${doc}`" :params="baseParams" :disabled="!ready"
          :label="`Compare ${doc}`" />
      </div>

      <!-- Report -->
      <div class="form-section">
        <h3 class="step">Validation report</h3>
        <span v-if="reportNote" class="field-help">{{ reportNote }}</span>
        <div v-if="report" class="panel">
          <div class="counts">
            <span>{{ report.files_in_range }} of {{ report.files_scanned }} files in range</span>
            <span :class="report.blocking_count ? 'bad' : 'ok'">{{ report.blocking_count }} blocking</span>
            <span>{{ report.non_blocking_count }} advisory</span>
            <span v-if="report.range.gaps.length">gaps: {{ report.range.gaps.join(', ') }}</span>
            <span v-if="report.existing_corpus">corpus: {{ report.existing_corpus.state }}</span>
          </div>
          <div v-if="duplicates.length" class="findings">
            <h4>Possible duplicates ({{ duplicates.length }})</h4>
            <p class="field-help">Review only. Rule on a pair in canon.yaml to silence it; nothing is merged for you.</p>
            <ul>
              <li v-for="(f, i) in duplicates" :key="'d' + i">
                <code>{{ f.file }}<template v-if="f.line">:{{ f.line }}</template></code> {{ f.message }}
              </li>
            </ul>
          </div>
          <div v-if="otherFindings.length" class="findings">
            <h4>Findings ({{ otherFindings.length }})</h4>
            <ul>
              <li v-for="(f, i) in otherFindings" :key="'f' + i" :class="{ bad: f.blocking }">
                <strong>{{ f.blocking ? 'BLOCK' : 'note' }}</strong>
                <code>{{ f.code }}</code>
                <code>{{ f.file }}<template v-if="f.line">:{{ f.line }}</template></code>
                {{ f.message }}
              </li>
            </ul>
          </div>
        </div>
      </div>

      <!-- Drafts -->
      <div class="form-section">
        <h3 class="step">Drafts</h3>
        <span v-if="draftsNote" class="field-help">{{ draftsNote }}</span>
        <table v-if="drafts.length" class="drafts">
          <thead><tr><th>Document</th><th>Status</th><th>Size</th><th>Path</th></tr></thead>
          <tbody>
            <tr v-for="d in drafts" :key="d.path">
              <td>{{ d.doc }}</td>
              <td :class="d.status === 'incomplete' ? 'bad' : d.status === 'draft' ? 'ok' : ''">{{ d.status }}</td>
              <td>{{ d.bytes }} B</td>
              <td><code>{{ d.path }}</code></td>
            </tr>
          </tbody>
        </table>
        <span v-if="drafts.length" class="field-help">
          An incomplete draft failed its outline check and is not promotable. A report is read-only evidence
          (drops.md lists every dropped note; npc_status_report.md the merged, unresolved and player-character names;
          canon_events_timeline.md every event in order; audit.md every tracking-item verdict; annotations.md every annotation and removal; key_npcs_report.md
          who was selected for Key NPCs and what code replaced; reference/*.md every checked note by subject, which each
          world_state section and campaign_state's thread sections point to).
          Review a draft in your editor; promotion is manual.
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 1400px; height: 100%; overflow-y: auto; box-sizing: border-box; }
.page-header { margin-bottom: 20px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }

.form-grid { display: flex; flex-direction: column; gap: 16px; }
.form-section { padding-bottom: 12px; border-bottom: 1px solid var(--bg-surface0); }
.form-section:last-child { border-bottom: none; }
.step { font-size: 12px; font-weight: 700; color: var(--text); margin-bottom: 8px; }

.field { margin-bottom: 10px; }
.field-label { display: block; font-size: 11px; font-weight: 600; color: var(--text-sub); margin-bottom: 3px; }
.field-input, .field-textarea {
  width: 100%; padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-base);
  color: var(--text); font-family: var(--mono); font-size: 11px;
  outline: none; box-sizing: border-box;
}
.field-input.narrow { width: 160px; }
.field-textarea { resize: vertical; }
.field-input:focus, .field-textarea:focus { border-color: var(--mauve); }
.field-help { display: block; font-size: 10px; color: var(--text-muted); margin-top: 3px; }
.field-error { display: block; font-size: 11px; color: var(--red); margin-top: 4px; }

.range-row { display: flex; align-items: center; gap: 8px; }
.range-sep { font-size: 11px; color: var(--text-muted); }
.num-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 0 16px; }

.checkbox-label { font-size: 11px; color: var(--text-sub); display: flex; align-items: center; gap: 6px; cursor: pointer; margin-bottom: 8px; }
.checkbox-label input { accent-color: var(--mauve); }

.panel { padding: 10px; background: var(--bg-mantle); border-radius: 4px; font-size: 11px; color: var(--text-sub); }
.counts { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 8px; }
.findings h4 { font-size: 11px; font-weight: 700; color: var(--text); margin: 8px 0 4px; }
.findings ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 3px; }
.findings code, .drafts code { font-family: var(--mono); font-size: 10px; margin-right: 6px; }
.ok { color: var(--green); }
.bad { color: var(--red); }

.drafts { border-collapse: collapse; font-size: 11px; color: var(--text-sub); margin-top: 6px; }
.drafts th, .drafts td { text-align: left; padding: 3px 14px 3px 0; }
.drafts th { font-weight: 600; color: var(--text); }
.extract-state, .audit-state, .budgets, .missing-npcs, .annotations { margin-top: 10px; }
.chunks tr.outlier td { background: color-mix(in srgb, var(--red) 14%, transparent); }
.authority-actions { display: flex; flex-direction: column; gap: 10px; margin-top: 10px; }
.authority-actions .field { margin-bottom: 0; }
.authority-actions .btn-neutral { margin: 6px 6px 0 0; }
.authority-buttons { white-space: nowrap; }
.authority-diff, .authority-history { max-height: 260px; overflow: auto; white-space: pre-wrap; padding: 8px; background: var(--bg-base); border: 1px solid var(--bg-surface1); border-radius: 4px; color: var(--text-sub); font: 10px var(--mono); }
</style>
