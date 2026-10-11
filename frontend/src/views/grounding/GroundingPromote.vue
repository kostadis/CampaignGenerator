<script setup lang="ts">
import { ref, computed, watch, onMounted, type Ref } from 'vue'
import { apiFetch } from '../../api/client'
import { useConfigStore } from '../../stores/config'
import { useGroundingRun } from '../../composables/useGroundingRun'
import GroundingClaims from '../../components/GroundingClaims.vue'
import GroundingPromotion from '../../components/GroundingPromotion.vue'

// Claims & promotion (spec 037): checks the drafted bundle and publishes it, off the Summary-native build
// flow. The chapter range is the same stored one (grounding.yaml summary_native.range_since/until), so
// changing it here changes it on Summary-native too.
type Num = number | '' | null
const config = useConfigStore()
const summariesDir = ref('')
const rangeSince = ref<Num>(null)
const rangeUntil = ref<Num>(null)
function persisted(r: Ref<Num>) {
  return computed<number | null>({
    get: () => (typeof r.value === 'number' ? r.value : null),
    set: v => { r.value = v },
  })
}
useGroundingRun('summary_native', {
  summaries_dir: summariesDir,
  range_since: persisted(rangeSince),
  range_until: persisted(rangeUntil),
})

const chapters = ref<number[]>([])
const chaptersError = ref('')
async function loadChapters() {
  chaptersError.value = ''
  chapters.value = []
  const dir = summariesDir.value.trim()
  if (!dir) return
  try {
    const r = await apiFetch<{ present: number[] }>(
      `/api/grounding/summary-native/chapters?summaries_dir=${encodeURIComponent(dir)}`)
    chapters.value = r.present ?? []
  } catch (e) {
    chaptersError.value = e instanceof Error ? e.message : String(e)
  }
}
watch(summariesDir, loadChapters)
onMounted(async () => {
  await (config.groundingConfig ?? config.refreshGrounding())
  setTimeout(loadChapters, 50)
})
function selectAll() {
  if (!chapters.value.length) return
  rangeSince.value = chapters.value[0]
  rangeUntil.value = chapters.value[chapters.value.length - 1]
}
const since = computed(() => (typeof rangeSince.value === 'number' ? rangeSince.value : null))
const until = computed(() => (typeof rangeUntil.value === 'number' ? rangeUntil.value : null))

const sharedClaimsReview = ref('claims-review')
const sharedClaimsSelection = ref('')
const sharedClaimsReport = ref('')
function claimsSelectionSaved(path: string) { sharedClaimsSelection.value = path; if (!path) sharedClaimsReport.value = '' }
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Claims &amp; promotion</h2>
      <p class="subtitle">
        Check the drafted bundle for cross-document conflicts, then publish the four documents, timeline and
        references together. Drafts are built on <RouterLink to="/grounding/summary-native">Summary-native</RouterLink>;
        sign-offs are recorded on <RouterLink to="/grounding/review">Shared review</RouterLink>.
      </p>
      <p v-if="sharedClaimsSelection" class="subtitle selection-line" data-test="shared-claims-selection">
        Current server-saved claims selection: <code>{{ sharedClaimsSelection }}</code>
      </p>
    </div>

    <div class="range">
      <label class="field-label">Chapter range <span class="shared">(shared with Summary-native)</span></label>
      <div v-if="chapters.length" class="range-row">
        <select class="field-input narrow" v-model="rangeSince" aria-label="First chapter">
          <option :value="null" disabled>first&hellip;</option>
          <option v-for="c in chapters" :key="c" :value="c">{{ c }}</option>
        </select>
        <span class="range-sep">to</span>
        <select class="field-input narrow" v-model="rangeUntil" aria-label="Last chapter">
          <option :value="null" disabled>last&hellip;</option>
          <option v-for="c in chapters" :key="c" :value="c">{{ c }}</option>
        </select>
        <button class="btn-neutral btn-sm" @click="selectAll">All chapters</button>
      </div>
      <span v-else class="field-help">
        {{ summariesDir.trim() ? 'No numbered summaries found in the Summary-native summaries directory.' : 'Set the summaries directory on Summary-native to list its chapters.' }}
      </span>
      <span v-if="chaptersError" class="field-error">{{ chaptersError }}</span>
    </div>

    <GroundingClaims
      :since="since" :until="until"
      :review-id="sharedClaimsReview" @review-changed="sharedClaimsReview=$event"
      @selection-saved="claimsSelectionSaved" @report-ready="sharedClaimsReport=$event" />
    <GroundingPromotion
      :since="since" :until="until"
      :review-id="sharedClaimsReview" :check-report-path="sharedClaimsReport"
      @review-changed="sharedClaimsReview=$event" />
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 1400px; height: 100%; overflow-y: auto; box-sizing: border-box; }
.page-header { margin-bottom: 20px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }
.selection-line { margin-top: 6px; }
.selection-line code { font-family: var(--mono); font-size: 11px; }
.range { padding-bottom: 12px; }
.field-label { display: block; font-size: 11px; font-weight: 600; color: var(--text-sub); margin-bottom: 3px; }
.shared { font-weight: 400; color: var(--text-muted); }
.field-input {
  padding: 6px 8px; border-radius: 4px; border: 1px solid var(--bg-surface1); background: var(--bg-base);
  color: var(--text); font-family: var(--mono); font-size: 11px; outline: none; box-sizing: border-box;
}
.field-input.narrow { width: 160px; }
.field-input:focus { border-color: var(--mauve); }
.field-help { display: block; font-size: 10px; color: var(--text-muted); margin-top: 3px; }
.field-error { display: block; font-size: 11px; color: var(--red); margin-top: 4px; }
.range-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.range-sep { font-size: 11px; color: var(--text-muted); }
</style>
