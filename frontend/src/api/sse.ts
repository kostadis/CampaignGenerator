/**
 * SSE helper — connects to a streaming endpoint and calls back with text chunks.
 */

export interface SSECallbacks {
  onData: (text: string) => void
  onDone: (returncode: number) => void
  onError: (err: Event) => void
}

export function connectSSE(url: string, callbacks: SSECallbacks): EventSource {
  const es = new EventSource(url)

  es.onmessage = (e) => {
    callbacks.onData(JSON.parse(e.data))
  }

  es.addEventListener('done', (e) => {
    es.close()
    const data = JSON.parse((e as MessageEvent).data)
    callbacks.onDone(data.returncode)
  })

  es.onerror = (e) => {
    es.close()
    callbacks.onError(e)
  }

  return es
}
