import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiFetch, apiPut } from '../api/client'

export const useConfigStore = defineStore('config', () => {
  // Legacy flat-key mirror of the response. Still populated from the server
  // response (which includes a flat-key overlay for back-compat) so views
  // that read ``config.values.sd_*`` keep working until they're migrated.
  const values = ref<Record<string, any>>({})

  // Typed/resolved view from the unified config service. Path fields are
  // absolute against campaign_dir. Views migrating off the flat overlay
  // should read from here: ``config.resolved.ui.session_doc.narrate_tokens``.
  const resolved = ref<Record<string, any>>({})

  // Surface migration warnings so the UI can render a banner when an old
  // ui_config.yaml was migrated and any keys were coerced or quarantined.
  const migrationWarnings = ref<string[]>([])

  const models = ref<string[]>([])
  const defaultModel = ref('claude-sonnet-4-6')
  const model = ref('claude-sonnet-4-6')
  const apiKeyPresent = ref(false)
  const cwd = ref('')
  const loaded = ref(false)
  let loadPromise: Promise<void> | null = null

  async function load() {
    if (loadPromise) return loadPromise
    loadPromise = (async () => {
      const [cfg, modelsData, status] = await Promise.all([
        apiFetch('/api/config/'),
        apiFetch('/api/config/models'),
        apiFetch('/api/config/status'),
      ])
      values.value = cfg
      resolved.value = cfg.resolved ?? {}
      migrationWarnings.value = cfg.migration_warnings ?? []
      models.value = modelsData.models
      defaultModel.value = modelsData.default
      model.value = cfg.global_model || modelsData.default
      apiKeyPresent.value = status.api_key_present
      cwd.value = status.cwd
      loaded.value = true
    })()
    return loadPromise
  }

  // Refetch and update the typed view + legacy mirror after a typed write.
  async function refresh() {
    const cfg = await apiFetch('/api/config/')
    values.value = cfg
    resolved.value = cfg.resolved ?? {}
    migrationWarnings.value = cfg.migration_warnings ?? []
  }

  // Typed-section update — preferred over the legacy bulk save for any
  // value that lives in ui.<section>.<field>. Persists atomically through
  // the unified service, then refreshes the local mirror.
  async function updateSection(name: string, partial: Record<string, any>) {
    if (!loaded.value) return
    await apiPut(`/api/config/section/${name}`, { values: partial })
    await refresh()
  }

  // Local (machine-only) update — server.host/port, transient nav state.
  async function updateLocal(partial: Record<string, any>) {
    if (!loaded.value) return
    await apiPut('/api/config/local', { values: partial })
    await refresh()
  }

  // Runtime update — session_dir, default_model. Backed by ui_state.runtime.
  async function updateRuntime(partial: Record<string, any>) {
    if (!loaded.value) return
    await apiPut('/api/config/runtime', { values: partial })
    await refresh()
  }

  return {
    values,
    resolved,
    migrationWarnings,
    models,
    defaultModel,
    model,
    apiKeyPresent,
    cwd,
    loaded,
    load,
    updateSection,
    updateLocal,
    updateRuntime,
    refresh,
  }
})
