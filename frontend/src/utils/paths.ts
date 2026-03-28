import { useConfigStore } from '../stores/config'

/**
 * Resolve a path against session_dir if it's relative.
 * Absolute paths (starting with / or ~) are returned as-is.
 */
export function resolvePath(raw: string): string {
  const trimmed = raw.trim()
  if (!trimmed) return ''
  if (trimmed.startsWith('/') || trimmed.startsWith('~')) return trimmed
  const config = useConfigStore()
  const sd = (config.values.session_dir || '').trim()
  if (sd) return `${sd.replace(/\/+$/, '')}/${trimmed}`
  return trimmed
}

/**
 * Resolve each line in a newline-separated string.
 */
export function resolvePathList(raw: string): string[] {
  return raw.split('\n').map(l => l.trim()).filter(Boolean).map(resolvePath)
}
