import { ref, watch, onMounted, type Ref } from 'vue'
import { useConfigStore } from '../stores/config'

/**
 * Load-and-persist for one grounding doc's section of `grounding.yaml`.
 *
 * Phase 9 of docs/config/grounding-isolation.md. Before this, each of the four
 * pages hand-rolled its own load + (sometimes) persist:
 *
 *   - CampaignState.vue and DistillWorldState.vue read six keys on mount and
 *     NEVER wrote them. `ui.campaign_state` and `ui.distill` were write-never
 *     sections: every value the GM typed was lost on reload, recoverable only
 *     by hand-editing ui_state.yaml.
 *   - PartyDocument.vue persisted 2 of the 9 fields it read; PlanningDocument
 *     .vue 2 of 12. The rest were dead reads against keys nothing wrote.
 *
 * One helper so a field cannot be added to the form and silently not persist:
 * the same `fields` object is both what gets loaded and what gets saved.
 */
export function useGroundingRun<T extends Record<string, Ref<any>>>(
  doc: 'campaign_state' | 'distill' | 'party' | 'planning',
  fields: T,
  opts: { debounceMs?: number } = {},
) {
  const config = useConfigStore()
  const loading = ref(true)
  /** Suppresses the save-on-change watcher while load() populates the refs. */
  let hydrating = true

  /** The shared canonical-timeline pointer (grounding.yaml's root). */
  const sharedSummaries = ref('')

  async function load() {
    loading.value = true
    hydrating = true
    try {
      const cfg = config.groundingConfig ?? (await config.refreshGrounding())
      sharedSummaries.value = cfg?.summaries ?? ''
      const section = (cfg?.[doc] ?? {}) as Record<string, any>
      for (const [key, r] of Object.entries(fields)) {
        const v = section[key]
        if (v === undefined || v === null) continue
        r.value = v
      }
    } finally {
      loading.value = false
      // Let the just-assigned values settle before re-arming the watcher,
      // otherwise hydration itself triggers a save.
      setTimeout(() => { hydrating = false }, 0)
    }
  }

  function snapshot(): Record<string, any> {
    const out: Record<string, any> = {}
    for (const [key, r] of Object.entries(fields)) out[key] = r.value
    return out
  }

  let timer: ReturnType<typeof setTimeout> | null = null
  function persist() {
    if (hydrating) return
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => {
      // Non-fatal: the local refs still hold the value, so a failed save
      // degrades to "not persisted", never to "field cleared".
      config.updateGrounding({ [doc]: snapshot() }).catch(() => {})
    }, opts.debounceMs ?? 600)
  }

  /** Update the shared root `summaries` pointer (not this doc's section). */
  async function saveSharedSummaries(value: string) {
    sharedSummaries.value = value
    await config.updateGrounding({ summaries: value || null })
  }

  watch(Object.values(fields), persist, { deep: true })
  onMounted(load)

  return { load, persist, loading, sharedSummaries, saveSharedSummaries }
}
