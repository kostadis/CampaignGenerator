/**
 * Simple fetch wrapper — all API calls go through here.
 */

const BASE = ''  // Same origin; Vite proxies /api/* in dev

export class ApiError<T = unknown> extends Error {
  readonly status: number
  readonly data: T | null

  constructor(status: number, data: T | null, fallback: string) {
    const serverMessage = (
      data !== null
      && typeof data === 'object'
      && 'error' in data
      && typeof data.error === 'string'
    ) ? data.error : fallback
    super(`API ${status}: ${serverMessage || 'Request failed'}`)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

export async function apiFetch<T = any>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, options)
  if (!res.ok) {
    const text = await res.text()
    let data: unknown = null
    try {
      data = JSON.parse(text)
    } catch {
      // Preserve non-JSON failures through the fallback message.
    }
    throw new ApiError(res.status, data, text)
  }
  return res.json()
}

export async function apiPut<T = any>(path: string, body: any): Promise<T> {
  return apiFetch(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export async function apiPost<T = any>(path: string, body?: any): Promise<T> {
  const options: RequestInit = { method: 'POST' }
  if (body !== undefined) {
    options.headers = { 'Content-Type': 'application/json' }
    options.body = JSON.stringify(body)
  }
  return apiFetch(path, options)
}

export async function apiDelete<T = any>(path: string): Promise<T> {
  return apiFetch(path, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' }
  })
}
