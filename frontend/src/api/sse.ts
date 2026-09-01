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

export type PostSSECallbacks = Omit<SSECallbacks, 'onError'> & {
  onError: (err: Error) => void
}

/**
 * Stream a POST action whose body is JSON. Native EventSource cannot send a
 * request body, so narration-wiki uses fetch + ReadableStream and parses SSE
 * frames incrementally. Frames may be split at any byte boundary.
 */
export async function streamPostSSE(
  url: string,
  body: unknown,
  callbacks: PostSSECallbacks,
  signal?: AbortSignal,
): Promise<void> {
  try {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify(body),
      signal,
    })
    if (!response.ok || !response.body) {
      throw new Error(`Stream request failed (${response.status})`)
    }
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    const dispatch = (frame: string) => {
      let event = 'message'
      const data: string[] = []
      for (const line of frame.replace(/\r\n/g, '\n').split('\n')) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        if (line.startsWith('data:')) data.push(line.slice(5).trimStart())
      }
      if (!data.length) return
      const payload = data.join('\n')
      if (event === 'command') {
        callbacks.onCommand?.(JSON.parse(payload) as string)
      } else if (event === 'done') {
        const done = JSON.parse(payload) as { returncode: number; error?: string }
        callbacks.onDone(done.returncode, done.error)
      } else {
        callbacks.onData(JSON.parse(payload) as string)
      }
    }

    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      buffer = buffer.replace(/\r\n/g, '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        dispatch(buffer.slice(0, boundary))
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
      }
      if (done) break
    }
    if (buffer.trim()) dispatch(buffer)
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    callbacks.onError(error instanceof Error ? error : new Error(String(error)))
  }
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
