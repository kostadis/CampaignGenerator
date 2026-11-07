/**
 * Client for `/api/summary-native/delta` (spec 039, contracts/http.md).
 *
 * Thin by design (Principle VI): every function is one route. Nothing is cached or
 * remembered here (Principle IX) — state lives on disk and is re-read through
 * `fetchStatus`. Sources are always an explicit list (Principle X); backend and model are
 * never sent from the page, the router resolves them from the owning config model.
 */
import { apiFetch, apiPost } from './client'

export const DELTA_BASE = '/api/summary-native/delta'

export type RunStatusName =
  | 'running' | 'failed' | 'stale' | 'awaiting_review' | 'partial' | 'recovery_required' | 'complete'

export interface StageArtifact { path: string; sha256: string }
export interface StageRecord {
  name: string
  status: string
  artifacts: StageArtifact[]
  started_at?: string | null
  finished_at?: string | null
}
export interface MemberRecord { subject: string; outcome: string; receipt_ref?: string | null }
export interface DeltaStatus {
  run_id?: string
  status: RunStatusName
  stages: StageRecord[]
  members?: MemberRecord[]
  counts?: Record<string, unknown>
  next_action?: string
  recovery_command?: string
  message?: string
  [key: string]: unknown
}

export type Decision = 'approve' | 'reject' | 'discuss'
export const DECISIONS: readonly Decision[] = ['approve', 'reject', 'discuss']

const planPath = (planId: string) => `${DELTA_BASE}/plans/${encodeURIComponent(planId)}`

export interface ChapterFile { chapter: number; path: string }
export interface ChapterListing { present: number[]; files: ChapterFile[]; duplicate_chapters?: number[] }

/** Existing summary-native chapters listing; `path` is a file name under `summariesDir`. */
export function fetchChapters(summariesDir: string): Promise<ChapterListing> {
  return apiFetch(`/api/grounding/summary-native/chapters?summaries_dir=${encodeURIComponent(summariesDir)}`)
}

/** POST /plans — body `{sources: string[], product: string[], stop?}`. Never a flag or glob. */
export function createPlan(sources: string[], product: string[], stop?: string) {
  const body: Record<string, unknown> = { sources, product }
  if (stop) body.stop = stop
  return apiPost(`${DELTA_BASE}/plans`, body)
}

export const fetchStatus = (planId: string) => apiFetch<DeltaStatus>(`${planPath(planId)}/status`)
export const fetchBaseline = (planId: string) => apiFetch(`${planPath(planId)}/baseline`)
export const fetchReceipt = (planId: string) => apiFetch(`${planPath(planId)}/receipt`)
export const fetchReview = (planId: string) => apiFetch(`${planPath(planId)}/review`)
export const reviewHandoff = (planId: string) => apiPost(`${planPath(planId)}/review/handoff`, {})
export const ingestSources = (planId: string) => apiPost(`${planPath(planId)}/sources`, {})

/**
 * POST /associations/{id}/decision — body `{plan, decision, reviewer, reason?}`; decision and reviewer are
 * explicit (the CLI refuses a decision with no reviewer, exit 2), plan is required by the CLI.
 */
export function decideAssociation(id: string, decision: Decision, reviewer: string, reason?: string, plan?: string) {
  return apiPost(`${DELTA_BASE}/associations/${encodeURIComponent(id)}/decision`, body(decision, reviewer, reason, plan))
}

/** POST /grounding/proposals/{id}/decision — body `{plan?, decision, reviewer, reason?}`. */
export function decideProposal(id: string, decision: Decision, reviewer: string, reason?: string, plan?: string) {
  return apiPost(`${DELTA_BASE}/grounding/proposals/${encodeURIComponent(id)}/decision`, body(decision, reviewer, reason, plan))
}

function body(decision: Decision, reviewer: string, reason?: string, plan?: string) {
  const out: Record<string, string> = { decision, reviewer }
  if (reason) out.reason = reason
  if (plan) out.plan = plan
  return out
}

/** POST /plans/{id}/npc/{subject}/attest — body `{reason, publication}`; both required. */
export function attestUnchanged(planId: string, subject: string, reason: string, publication: string) {
  return apiPost(`${planPath(planId)}/npc/${encodeURIComponent(subject)}/attest`, { reason, publication })
}

/** POST /plans/{id}/grounding/preview — body `{}`; the response carries the preview sha. */
export const previewGrounding = (planId: string) => apiPost(`${planPath(planId)}/grounding/preview`, {})

// ── streamed stages ────────────────────────────────────────────────────────

export interface StreamResult { exitCode: number; lines: string[] }

/** Parse `event: line` / `event: exit` (and the shared helper's default / `done`) frames. */
export async function streamStage(
  path: string, reqBody: unknown, onLine?: (line: string) => void,
): Promise<StreamResult> {
  const res = await fetch(`${DELTA_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(reqBody ?? {}),
  })
  if (!res.ok || !res.body) {
    const text = res.body ? await res.text() : ''
    throw new Error(`API ${res.status}: ${text || 'stream request failed'}`)
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  const lines: string[] = []
  let exitCode = -1
  let buffer = ''
  const dispatch = (frame: string) => {
    let event = 'message'
    const data: string[] = []
    for (const l of frame.split('\n')) {
      if (l.startsWith('event:')) event = l.slice(6).trim()
      if (l.startsWith('data:')) data.push(l.slice(5).trimStart())
    }
    if (!data.length) return
    const payload = data.join('\n')
    if (event === 'exit' || event === 'done') {
      const p = JSON.parse(payload)
      exitCode = typeof p === 'number' ? p : Number(p.exit_code ?? p.returncode ?? p.code ?? -1)
    } else if (event === 'line' || event === 'message') {
      let text = payload
      try { const p = JSON.parse(payload); text = typeof p === 'string' ? p : payload } catch { /* raw */ }
      lines.push(text)
      onLine?.(text)
    }
  }
  while (true) {
    const { value, done } = await reader.read()
    buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, '\n')
    let i = buffer.indexOf('\n\n')
    while (i >= 0) { dispatch(buffer.slice(0, i)); buffer = buffer.slice(i + 2); i = buffer.indexOf('\n\n') }
    if (done) break
  }
  if (buffer.trim()) dispatch(buffer)
  return { exitCode, lines }
}

export type StreamStageName =
  | 'census' | 'associations/propose' | 'npc/draft' | 'npc/verify'
  | 'grounding/propose' | 'grounding/check' | 'resume'

export const runStage = (planId: string, stage: StreamStageName, onLine?: (l: string) => void) =>
  streamStage(`/plans/${encodeURIComponent(planId)}/${stage}`, {}, onLine)

export interface NpcPublishPreview {
  plan_id?: string
  preview_sha256: string
  members: { subject: string; slug: string; [key: string]: unknown }[]
  published?: boolean
}

/**
 * POST /plans/{id}/npc/publish/preview — body `{members}`. The CLI's own preview (no `--preview-sha`):
 * writes nothing and returns the digest the GM confirms before publishing.
 */
export function previewNpcPublish(planId: string, members: string[]): Promise<NpcPublishPreview> {
  if (!members.length) throw new Error('no members selected; npc publish needs an explicit member list.')
  return apiPost(`${planPath(planId)}/npc/publish/preview`, { members }) as Promise<NpcPublishPreview>
}

/** POST /plans/{id}/npc/publish — body `{members, preview_sha}`: an explicit list plus a previewed digest. */
export function publishNpcs(planId: string, members: string[], previewSha: string, onLine?: (l: string) => void) {
  if (!members.length) throw new Error('no members selected; npc publish needs an explicit member list.')
  if (!previewSha) throw new Error('preview the NPC publication first; publishing needs its sha.')
  return streamStage(`/plans/${encodeURIComponent(planId)}/npc/publish`, { members, preview_sha: previewSha }, onLine)
}

/** POST /plans/{id}/grounding/apply — body `{preview_sha}`. */
export function applyGrounding(planId: string, previewSha: string, onLine?: (l: string) => void) {
  return streamStage(`/plans/${encodeURIComponent(planId)}/grounding/apply`, { preview_sha: previewSha }, onLine)
}
