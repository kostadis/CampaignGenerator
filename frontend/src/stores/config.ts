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

  // Typed/resolved view from the platform config service — path fields
  // absolute against campaign_dir. Four keys: campaign_dir, runtime, server,
  // nav. It carried a fifth, `ui`, until
  // docs/config/ui-state-retirement.md; per-service config now comes from
  // that service's own document (editorConfig / groundingConfig below, or a
  // dedicated fetch), never from here.
  const resolved = ref<Record<string, any>>({})

  // Surface migration warnings so the UI can render a banner when an old
  // ui_config.yaml was migrated and any keys were coerced or quarantined.
  const migrationWarnings = ref<string[]>([])

  // The Session Doc Editor's grouped, resolved configuration — the single
  // source of truth for the editor (GET /api/editor/config):
  // paths/narrate/roster/backends/session_name/profiles/
  // active_profile plus read-only platform extras (model, work_dir,
  // campaign_dir, config_dir, vtt). See
  // docs/config/session-editor-isolation.md.
  const editorConfig = ref<Record<string, any> | null>(null)

  // ── Grounding docs — /api/grounding/config ────────────────────────
  // The four grounding pages' own document (<config>/grounding.yaml, owned by
  // GroundingConfigService). Replaces ui.grounding + ui.campaign_state +
  // ui.distill + ui.party + ui.planning — two of which were WRITE-NEVER
  // sections whose values evaporated on reload, and two of which persisted a
  // handful of the fields they read. See docs/config/grounding-isolation.md.
  const groundingConfig = ref<Record<string, any> | null>(null)

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
  // The app-wide backend. Feature 003 moved it out of the Session Doc
  // Editor's backends.active (session_doc.yaml) and up to the platform tier
  // beside default_model, so the sidebar's two controls are owned by the same
  // thing. Before that, editing the Session Doc Editor silently re-targeted
  // every Grounding run, and a command could carry a model from one owner and
  // a backend from another. The editor keeps its own backends block — it is a
  // legitimate per-service override now, just no longer the global value.
  const backend = ref<string>('anthropic')
  const backends = ref<string[]>([])
  // The app-wide batch flag (005-ui-batch-selection). Same tier and write
  // path as `backend` — PUT /api/config/runtime is the ONLY app-wide write
  // door (feature 003) — so it is hydrated and refreshed identically. Every
  // SelectionPanel re-resolves on a change here (see its `watch`), which is
  // how flipping this in the sidebar shows up as "inherited" everywhere else
  // without a page reload.
  const batch = ref<boolean>(false)
  const apiKeyPresent = ref(false)
  const cwd = ref('')
  const loaded = ref(false)
  let loadPromise: Promise<void> | null = null

  async function load() {
    if (loadPromise) return loadPromise
    loadPromise = (async () => {
      const [cfg, modelsData, status, editorCfg, groundingCfg] = await Promise.all([
        apiFetch('/api/config/'),
        apiFetch('/api/config/models'),
        apiFetch('/api/config/status'),
        apiFetch('/api/editor/config'),
        // Boot-loaded like editorConfig: SessionConfig.vue and
        // QuerySummaries.vue read the shared `summaries` pointer off it on
        // mount, so a lazy first fetch would leave those fields blank.
        apiFetch('/api/grounding/config'),
      ])
      values.value = cfg
      resolved.value = cfg.resolved ?? {}
      migrationWarnings.value = cfg.migration_warnings ?? []
      models.value = modelsData.models
      defaultModel.value = modelsData.default
      backends.value = modelsData.backends || ['anthropic', 'dgx', 'openrouter', 'claude-code']
      backend.value = cfg.resolved?.runtime?.default_backend || modelsData.default_backend || 'anthropic'
      model.value = cfg.resolved?.runtime?.default_model || modelsData.default
      batch.value = cfg.resolved?.runtime?.default_batch === true
      apiKeyPresent.value = status.api_key_present
      cwd.value = status.cwd
      editorConfig.value = editorCfg
      groundingConfig.value = groundingCfg
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
    if (resolved.value.runtime?.default_backend) backend.value = resolved.value.runtime.default_backend
    if (resolved.value.runtime?.default_model) model.value = resolved.value.runtime.default_model
    if (resolved.value.runtime?.default_batch !== undefined) {
      batch.value = resolved.value.runtime.default_batch === true
    }
  }

  // Refetch the resolved editor config — call after any write that touches
  // the session-editor slice so ``editorConfig`` stays in sync.
  async function refreshEditor() {
    editorConfig.value = await apiFetch('/api/editor/config')
  }

  // `updateSection` lived here — a generic PUT /api/config/section/{name}
  // writer for ui_state.yaml's ui.<section> blobs. It had no callers, and the
  // sections it wrote were empty in every campaign, so the tier it served was
  // retired wholesale (docs/config/ui-state-retirement.md). Each service now
  // writes its own document: updateEditor, updateGrounding, updateRuntime,
  // updateLocal below, plus the ensemble/party/planning resource APIs.

  // Local (machine-only) update — server.host/port, transient nav state.
  async function updateLocal(partial: Record<string, any>) {
    if (!loaded.value) return
    await apiPut('/api/config/local', { values: partial })
    await refresh()
  }

  // Runtime update — session_dir, default_model, default_backend.
  // Backed by platform.yaml; the ONLY write path for the app-wide backend.
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

  async function refreshGrounding() {
    groundingConfig.value = await apiFetch('/api/grounding/config')
    return groundingConfig.value
  }

  /** Merge a grouped partial into grounding.yaml. The body IS the partial —
   *  no {values: ...} envelope (matches PUT /api/ensemble/config). */
  async function updateGrounding(partial: Record<string, any>) {
    groundingConfig.value = await apiPut('/api/grounding/config', partial)
    return groundingConfig.value
  }

  return {
    values,
    resolved,
    migrationWarnings,
    editorConfig,
    groundingConfig,
    refreshGrounding,
    updateGrounding,
    models,
    backend,
    backends,
    batch,
    defaultModel,
    model,
    apiKeyPresent,
    cwd,
    loaded,
    load,
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
