/**
 * SSE helper — connects to a streaming endpoint and calls back with text chunks.
 */

export interface SSECallbacks {
  onData: (text: string) => void
  onDone: (returncode: number, error?: string) => void
  /** Called with the secret-free, copyable invocation from the `command` event (US1). */
  onCommand?: (cmd: string) => void
  /**
   * Called on connection error. During a running session the caller is
   * responsible for closing the EventSource — NOT this handler (I1: closing
   * inside onerror during 'running' would prevent the reconnect-as-abort logic
   * in useEnsembleRun from running its own teardown). In idle/done state the
   * caller may still close here via callbacks.onError handling.
   */
  onError: (err: Event) => void
}

export function connectSSE(url: string, callbacks: SSECallbacks): EventSource {
  const es = new EventSource(url)

  es.onmessage = (e) => {
    callbacks.onData(JSON.parse(e.data))
  }

  es.addEventListener('command', (e) => {
    if (callbacks.onCommand) {
      callbacks.onCommand(JSON.parse((e as MessageEvent).data))
    }
  })

  es.addEventListener('done', (e) => {
    es.close()
    const data = JSON.parse((e as MessageEvent).data)
    callbacks.onDone(data.returncode, data.error)
  })

  es.onerror = (e) => {
    callbacks.onError(e)
  }

  return es
}
