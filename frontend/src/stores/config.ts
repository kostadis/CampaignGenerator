import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiFetch, apiPut, apiPost, apiDelete } from '../api/client'

export const useConfigStore = defineStore('config', () => {
  // Raw mirror of the last GET /api/config/ response, plus a client-side-only
  // scratch bag: SessionConfig.vue broadcasts derived paths onto this object
  // (Object.assign) so sibling pages not yet migrated to ``resolved`` can
  // pick them up without a round trip. It is replaced wholesale — not
  // merged — on every load()/refresh(), so anything Object.assign'd onto it
  // evaporates on the next config fetch.
  const values = ref<Record<string, any>>({})

  // Typed/resolved view from the unified config service. Path fields are
  // absolute against campaign_dir. Views migrating off the flat overlay
  // should read from here: ``config.resolved.ui.session_doc.narrate_tokens``.
  const resolved = ref<Record<string, any>>({})

  // Surface migration warnings so the UI can render a banner when an old
  // ui_config.yaml was migrated and any keys were coerced or quarantined.
  const migrationWarnings = ref<string[]>([])

  // The Session Doc Editor's grouped, resolved configuration — the single
  // source of truth for the editor (GET /api/editor/config):
  // paths/narrate/scrub/roster/backends/session_name/profiles/
  // active_profile plus read-only platform extras (model, work_dir,
  // campaign_dir, config_dir, vtt). See
  // docs/config/session-editor-isolation.md.
  const editorConfig = ref<Record<string, any> | null>(null)

  const models = ref<string[]>([])
  // Empty until GET /api/config/models answers — deliberately NOT seeded with
  // a model id. A seed here is a second source for the default model, and a
  // live one: App.vue swallows a load() failure and load() memoizes its
  // rejected promise, so after one failed boot the seed sticks for the life
  // of the page. Every run view forwards `model: config.model`, and an
  // explicit request model is level 1 in resolve_default_model — it *beats*
  // runtime.default_model rather than falling through to it, so a stale seed
  // would silently override the GM's persisted pick. Empty is dropped from
  // the query string by RunPanel and is falsy in resolve_default_model, which
  // is exactly the fall-through we want. See docs/config/platform-isolation.md
  // ("one default-model source").
  const defaultModel = ref('')
  const model = ref('')
  const apiKeyPresent = ref(false)
  const cwd = ref('')
  const loaded = ref(false)
  let loadPromise: Promise<void> | null = null

  async function load() {
    if (loadPromise) return loadPromise
    loadPromise = (async () => {
      const [cfg, modelsData, status, editorCfg] = await Promise.all([
        apiFetch('/api/config/'),
        apiFetch('/api/config/models'),
        apiFetch('/api/config/status'),
        apiFetch('/api/editor/config'),
      ])
      values.value = cfg
      resolved.value = cfg.resolved ?? {}
      migrationWarnings.value = cfg.migration_warnings ?? []
      models.value = modelsData.models
      defaultModel.value = modelsData.default
      model.value = cfg.resolved?.runtime?.default_model || modelsData.default
      apiKeyPresent.value = status.api_key_present
      cwd.value = status.cwd
      editorConfig.value = editorCfg
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

  // Refetch the resolved editor config — call after any write that touches
  // the session-editor slice so ``editorConfig`` stays in sync.
  async function refreshEditor() {
    editorConfig.value = await apiFetch('/api/editor/config')
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

  // ── Session Doc Editor — the single write door ────────────────────
  // Grouped, possibly-nested SessionEditorConfig partial, e.g.
  // ``{narrate: {tokens: 8000}}`` or ``{backends: {active: 'dgx'}}``.
  // PUT /api/editor/config, then re-fetch so editorConfig reflects the
  // server's resolved view (paths absolute, boot overrides applied).
  async function updateEditor(partial: Record<string, any>) {
    await apiPut('/api/editor/config', partial)
    await refreshEditor()
  }

  // ── Profiles (Stage-④ knob presets) — /api/editor/profiles ────────
  // The list/active profile live on editorConfig.profiles/active_profile;
  // these mutate server-side and re-hydrate editorConfig afterward.
  async function createProfile(entry: { name: string; knobs: Record<string, any> }) {
    const created = await apiPost('/api/editor/profiles', entry)
    await refreshEditor()
    return created
  }

  async function updateProfile(name: string, entry: { name: string; knobs: Record<string, any> }) {
    const updated = await apiPut(`/api/editor/profiles/${encodeURIComponent(name)}`, entry)
    await refreshEditor()
    return updated
  }

  async function deleteProfile(name: string) {
    await apiDelete(`/api/editor/profiles/${encodeURIComponent(name)}`)
    await refreshEditor()
  }

  // Server-side activation (O2): mirrors the profile's narrate/backend
  // knobs into the stored config and marks it active, returning the
  // re-resolved editor config — same shape as GET /api/editor/config.
  async function activateProfile(name: string) {
    const cfg = await apiPost(`/api/editor/profiles/${encodeURIComponent(name)}/activate`)
    editorConfig.value = cfg
    return cfg
  }

  return {
    values,
    resolved,
    migrationWarnings,
    editorConfig,
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
    refreshEditor,
    updateEditor,
    createProfile,
    updateProfile,
    deleteProfile,
    activateProfile,
  }
})
