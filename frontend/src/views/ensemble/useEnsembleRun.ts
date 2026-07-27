import { ref } from 'vue'
import { apiFetch, apiPut } from '../../api/client'
import { connectSSE } from '../../api/sse'

/** Run an ensemble stage over SSE. Unlike RunPanel this does NOT gate on
 *  ANTHROPIC_API_KEY — the ensemble page supports OpenRouter/DGX backends that
 *  don't need it. */
export function useEnsembleRun() {
  const output = ref('')
  const status = ref<'idle' | 'running' | 'done' | 'error' | 'aborted'>('idle')
  const returnCode = ref<number | null>(null)
  /** Secret-free, copyable invocation from the server's `command` SSE event (US1). */
  const command = ref<string>('')

  // Private EventSource handle — kept so abort() can close it.
  let _es: EventSource | null = null

  function buildUrl(endpoint: string, params: Record<string, any>): string {
    const url = new URL(endpoint, window.location.origin)
    for (const [k, v] of Object.entries(params)) {
      if (v === '' || v === false || v === null || v === undefined) continue
      if (Array.isArray(v)) {
        for (const it of v) if (it) url.searchParams.append(k, String(it))
      } else if (typeof v === 'boolean') {
        url.searchParams.set(k, 'true')
      } else {
        url.searchParams.set(k, String(v))
      }
    }
    return url.pathname + url.search
  }

  function run(endpoint: string, params: Record<string, any>, onDone?: (rc: number) => void) {
    if (status.value === 'running') return
    status.value = 'running'
    output.value = ''
    returnCode.value = null
    command.value = ''
    _es = connectSSE(buildUrl(endpoint, params), {
      onCommand(cmd) { command.value = cmd },
      onData(t) { output.value += t },
      onDone(rc, error) {
        _es = null
        status.value = rc === 0 ? 'done' : 'error'
        returnCode.value = rc
        // Surface precondition refusals (FR-011): done.error carries the message.
        if (error && !output.value.includes(error)) {
          output.value += `\nError: ${error}\n`
        }
        if (onDone) onDone(rc)
      },
      onError(_e) {
        // I1: onerror during 'running' = network drop / disconnect.
        // Close the EventSource explicitly — prevents automatic reconnect which
        // would re-issue the GET and silently restart the run (metered calls!).
        // Treat as implicit abort; the server group-kills the process tree.
        if (status.value === 'running') {
          _es?.close()
          _es = null
          status.value = 'aborted'
          output.value += '\n[connection lost — run stopped]\n'
        } else {
          // Not running (e.g. initial connection failure) — just error out.
          _es?.close()
          _es = null
          status.value = 'error'
        }
      },
    })
  }

  /** Close the EventSource and mark status as aborted (valid only from 'running').
   *  The server observes the connection drop and group-kills the worker tree.
   */
  function abort() {
    if (status.value !== 'running') return
    _es?.close()
    _es = null
    status.value = 'aborted'
  }

  function clear() {
    output.value = ''
    status.value = 'idle'
    returnCode.value = null
    command.value = ''
  }

  return { output, status, returnCode, command, run, abort, clear }
}

// ── Ensemble config ────────────────────────────────────────────────────────
//
// Mirrors server/ensemble_config_shared.py's EnsembleConfig exactly. Phase 3
// of docs/config/ensemble-isolation.md: this file no longer declares ANY
// default of its own — it fetches them from GET /api/ensemble/config, which
// reads <config>/ensemble.yaml. Fallbacks here would be a third copy of the
// defaults, which is the drift the isolation work exists to remove.

export interface BackendProfile {
  backend: 'anthropic' | 'dgx' | 'openrouter' | 'claude-code'
  endpoints: string[]
  model: string
}

export interface EnsemblePaths {
  chapters_glob: string
  per_chapter_dir: string
  corpus_glob: string
  merged_out: string
  state_dossiers_dir: string
  dossiers_glob: string
  npc_dossiers_glob: string
  threads_out: string
  recent_events_out: string
  inventory: string
}

export interface EnsembleTuning {
  chapter_parallel: number
  chunk_parallel: number
  bundle_min_facts: number
  threads_min_facts: number
  dossier_min_facts: number
  entity_parallel: number
  recent_events_window: number
}

export interface EnsemblePlanning {
  synth_mode: 'config' | 'flat'
  npc: string[]
  arc_scores: string[]
  context: string[]
  depth: 'scene' | 'full'
  force_include: string[]
}

export interface EnsembleConfig {
  chapters_selected: string[]
  extract: BackendProfile
  synthesize: BackendProfile
  paths: EnsemblePaths
  tuning: EnsembleTuning
  planning: EnsemblePlanning
}

/** GET the campaign's ensemble.yaml. The server fills in every default. */
export async function fetchEnsembleConfig(): Promise<EnsembleConfig> {
  return apiFetch<EnsembleConfig>('/api/ensemble/config')
}

/** PUT a partial into ensemble.yaml; returns the merged, validated result.
 *  The body is the grouped partial itself — no {"values": …} envelope. */
export async function saveEnsembleConfig(
  partial: Record<string, unknown>,
): Promise<EnsembleConfig> {
  return apiPut<EnsembleConfig>('/api/ensemble/config', partial)
}

// ── Entity registry status (GET /api/ensemble/registry) ─────────────────────
//
// Mirrors server/routers/ensemble.py's ensemble_registry_status() response
// shape exactly. Consumed by EnsembleSetup (read-only summary), EnsembleBundle
// (the ② checkpoint + ③ gate), and EnsembleSynthesize (world_state pre-flight
// hint).

export interface RegistryCheck {
  grouping: string[]
  fuzzy: string[]
  missing_from_registry: string[]
  missing_from_legacy: string[]
  clean: boolean
}

export interface RegistrySummary {
  found: boolean
  path: string | null
  error: string | null
  entity_count?: number
  alias_count?: number
  types?: Record<string, number>
  check?: RegistryCheck
}

/** GET the campaign's entity-registry status. Always resolves — the route
 *  never 4xxs, "not found" and "invalid" are both states to render. */
export async function fetchRegistrySummary(): Promise<RegistrySummary> {
  return apiFetch<RegistrySummary>('/api/ensemble/registry')
}
