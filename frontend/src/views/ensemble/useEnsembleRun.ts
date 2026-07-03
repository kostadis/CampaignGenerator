import { ref } from 'vue'
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

export interface BackendProfile {
  backend: 'anthropic' | 'dgx' | 'openrouter'
  endpoint: string
  model: string
}

export interface EnsembleConfig {
  campaign_dir: string
  chapters_glob: string
  chapters_selected: string[]
  extract: BackendProfile
  synthesize: BackendProfile
  known_names: string[]
  aliases_path: string
}

/** Read ui.ensemble from the resolved config with safe defaults. */
export function readEnsembleConfig(resolved: any): EnsembleConfig {
  const e = resolved?.ui?.ensemble ?? {}
  const prof = (p: any): BackendProfile => ({
    backend: p?.backend ?? 'anthropic',
    endpoint: p?.endpoint ?? '',
    model: p?.model ?? '',
  })
  return {
    campaign_dir: e.campaign_dir ?? '',
    chapters_glob: e.chapters_glob ?? 'docs/chapters/chapter_*.md',
    chapters_selected: Array.isArray(e.chapters_selected) ? e.chapters_selected : [],
    extract: prof(e.extract),
    synthesize: prof(e.synthesize),
    known_names: Array.isArray(e.known_names) ? e.known_names : [],
    aliases_path: e.aliases_path ?? '',
  }
}
