import { useConfigStore } from '../stores/config'

export type ResolveBase = 'session' | 'campaign'

/**
 * Resolve a relative path against a base directory from config.
 * Absolute paths (starting with / or ~) are returned as-is.
 */
export function resolvePathWithBase(raw: string, base: ResolveBase = 'session'): string {
  const trimmed = raw.trim()
  if (!trimmed) return ''
  if (trimmed.startsWith('/') || trimmed.startsWith('~')) return trimmed
  const config = useConfigStore()
  const dir = base === 'campaign'
    ? (config.values.campaign_dir || '').trim()
    : (config.values.session_dir || '').trim()
  if (dir) return `${dir.replace(/\/+$/, '')}/${trimmed}`
  return trimmed
}

/**
 * Resolve a path against session_dir if it's relative.
 */
export function resolvePath(raw: string): string {
  return resolvePathWithBase(raw, 'session')
}

/**
 * Resolve each line in a newline-separated string against session_dir.
 */
export function resolvePathList(raw: string): string[] {
  return raw.split('\n').map(l => l.trim()).filter(Boolean).map(resolvePath)
}
