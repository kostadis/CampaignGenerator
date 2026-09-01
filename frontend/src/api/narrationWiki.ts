import { streamPostSSE, type PostSSECallbacks } from './sse'

export interface WikiScope {
  campaign_id: string
  session_relative: string
  iteration_id: string
}

export interface PatternCounts {
  pending: number
  accepted: number
  rejected: number
  pending_portable_sync: number
}

export interface WikiDependency {
  present: boolean
  compatible: boolean
  reason?: string | null
  source_repository?: string | null
  source_revision?: string | null
  capabilities: string[]
  manifest_sha256?: string | null
}

export interface WikiStatus extends WikiScope {
  ok: boolean
  command: 'status'
  state: string
  corpus_id: string | null
  pattern_counts: PatternCounts
  unresolved_conflict_ids: string[]
  active_proposal_id: string | null
  dependency: WikiDependency
  recovery: null | {
    transaction_id: string
    operation: string
    state: string
    next_action: string
  }
  measurement_checks?: MeasurementCheck[]
}

export interface MeasurementCheck {
  key: string
  scope: string
  subject: string | null
  observed: number | null
  budget: { operator: string; value: number; unit: string } | null
  verdict: 'ok' | 'breach' | 'skipped'
  reason: string | null
}

export interface EvidenceBinding {
  source_ref: string
  source_sha256: string
  applies_to_kind: 'rule' | 'measurement_category'
  applies_to_key: string
}

function query(scope: WikiScope): string {
  return new URLSearchParams(scope as unknown as Record<string, string>).toString()
}

export async function fetchWikiStatus(scope: WikiScope, signal?: AbortSignal): Promise<WikiStatus> {
  const response = await fetch(`/api/narration-wiki/status?${query(scope)}`, { signal })
  const payload = await response.json()
  if (!response.ok) throw new Error(payload.detail ?? `Status failed (${response.status})`)
  return payload as WikiStatus
}

export function runWikiAction(
  action: 'collect' | 'measure' | 'index-check' | 'conflict-rule' | 'pattern-rule'
    | 'proposal-stage' | 'proposal-apply' | 'proposal-rule',
  body: Record<string, unknown>,
  callbacks: PostSSECallbacks,
  signal?: AbortSignal,
): Promise<void> {
  return streamPostSSE(`/api/narration-wiki/${action}`, body, callbacks, signal)
}
