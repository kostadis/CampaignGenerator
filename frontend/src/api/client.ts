/**
 * Simple fetch wrapper — all API calls go through here.
 */

const BASE = ''  // Same origin; Vite proxies /api/* in dev

export async function apiFetch<T = any>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, options)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API ${res.status}: ${text}`)
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
