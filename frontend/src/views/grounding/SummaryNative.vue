<script setup lang="ts">
import { ref, computed, watch, onMounted, type Ref } from 'vue'
import { apiFetch } from '../../api/client'
import { useConfigStore } from '../../stores/config'
import { useGroundingRun } from '../../composables/useGroundingRun'
import PathField from '../../components/shared/PathField.vue'
import RunPanel from '../../components/shared/RunPanel.vue'

// summary_native (feature 031): grounding-doc drafts built straight from
// reviewed session summaries. This page invokes the `summary_native` CLI and
// reimplements none of it (FR-029). There is no promote button and no rulings
// editor: a draft is reviewed and promoted by hand, and the CLI-only paths
// (registry, canon, out-root) are set once in grounding.yaml, not per run.

const BASE = '/api/grounding/summary-native'
const SYNTH_ENDPOINT = '/api/grounding/summary-native/run/synth'
const DOCS = ['world_state', 'campaign_state', 'party', 'planning'] as const
type Doc = (typeof DOCS)[number]

const config = useConfigStore()

// ── Persisted fields (grounding.yaml summary_native) ────────────────────────
// Numeric inputs hold '' while a field is being retyped; that must not reach
// the strict schema, so the persisted view of a blank is `undefined` (dropped
// by JSON, leaving the stored value alone) or, for the range, an explicit null.
type Num = number | '' | null

const summariesDir = ref('')
const rangeSince = ref<Num>(null)
const rangeUntil = ref<Num>(null)
const dupThreshold = ref<Num>('')
const recentChapters = ref<Num>('')
const recurringMin = ref<Num>('')
const parts = ref<Num>('')

function persisted(r: Ref<Num>, nullable: boolean) {
  return computed<number | null | undefined>({
    get: () => (typeof r.value === 'number' ? r.value : nullable ? null : undefined),
    set: v => { r.value = v === undefined ? '' : v },
  })
}

useGroundingRun('summary_native', {
  summaries_dir: summariesDir,
  range_since: persisted(rangeSince, true),
  range_until: persisted(rangeUntil, true),
  dup_threshold: persisted(dupThreshold, false),
  recent_chapters: persisted(recentChapters, false),
  recurring_min: persisted(recurringMin, false),
  parts: persisted(parts, false),
})

// ── Per-run fields (not stored) ─────────────────────────────────────────────
const doc = ref<Doc>('world_state')
const worldStatePath = ref('')
const campaignStatePath = ref('')
const auditText = ref('')
const namesText = ref('')
const maxTokens = ref<Num>('')
const dumpOnly = ref(false)
const forceBuild = ref(false)
// Per-run, never persisted: replacing a reviewed draft must be a deliberate act each time.
const forceSynth = ref(false)

const lines = (t: string) => t.split('\n').map(l => l.trim()).filter(Boolean)
const num = (n: Num) => (typeof n === 'number' ? n : undefined)

// ── Chapters / range picker ─────────────────────────────────────────────────
interface Chapters {
  present: number[]
  files: { chapter: number; path: string }[]
  duplicate_chapters: number[]
}
const chapters = ref<Chapters | null>(null)
const chaptersError = ref('')
let chaptersTimer: ReturnType<typeof setTimeout> | null = null

async function loadChapters() {
  chaptersError.value = ''
  chapters.value = null
  const dir = summariesDir.value.trim()
  if (!dir) return
  try {
    chapters.value = await apiFetch<Chapters>(
      `${BASE}/chapters?summaries_dir=${encodeURIComponent(dir)}`,
    )
  } catch (e) {
    chaptersError.value = e instanceof Error ? e.message : String(e)
  }
}

watch(summariesDir, () => {
  if (chaptersTimer) clearTimeout(chaptersTimer)
  chaptersTimer = setTimeout(loadChapters, 400)
})

// "All chapters" is a deliberate choice: it writes the first and last chapter
// into the range explicitly, so the run (and the stored config) names them.
function selectAll() {
  const present = chapters.value?.present ?? []
  if (!present.length) return
  rangeSince.value = present[0]
  rangeUntil.value = present[present.length - 1]
}

const rangeChosen = computed(
  () => typeof rangeSince.value === 'number' && typeof rangeUntil.value === 'number',
)
const rangeInverted = computed(
  () => rangeChosen.value && (rangeSince.value as number) > (rangeUntil.value as number),
)
const ready = computed(() => !!summariesDir.value.trim() && rangeChosen.value && !rangeInverted.value)

// ── Run params ──────────────────────────────────────────────────────────────
const baseParams = computed(() => ({
  summaries_dir: summariesDir.value.trim(),
  since: num(rangeSince.value),
  until: num(rangeUntil.value),
}))
const validateParams = computed(() => ({
  ...baseParams.value, dup_threshold: num(dupThreshold.value),
}))
const buildParams = computed(() => ({
  ...baseParams.value, dup_threshold: num(dupThreshold.value), force: forceBuild.value,
}))
const synthParams = computed(() => ({
  ...baseParams.value,
  world_state: worldStatePath.value.trim(),
  campaign_state: campaignStatePath.value.trim(),
  audit: lines(auditText.value),
  name: lines(namesText.value),
  recent_chapters: num(recentChapters.value),
  recurring_min: num(recurringMin.value),
  parts: num(parts.value),
  max_tokens: num(maxTokens.value),
  dump_only: dumpOnly.value,
  force: forceSynth.value,
  model: config.model || undefined,
}))

// ── Report and drafts ───────────────────────────────────────────────────────
interface Finding {
  file: string; line: number | null; code: string; message: string
  expected: string | null; found: string | null; blocking: boolean; in_range: boolean
}
interface Report {
  range: { since: number; until: number; present: number[]; gaps: number[] }
  files_scanned: number; files_in_range: number
  blocking_count: number; files_failing: number; non_blocking_count: number
  findings: Finding[]
  existing_corpus?: { state: string; [k: string]: unknown }
}
interface DraftRow { doc: string; path: string; status: 'draft' | 'incomplete'; bytes: number }

const report = ref<Report | null>(null)
const reportNote = ref('')
const drafts = ref<DraftRow[]>([])
const draftsNote = ref('')

const duplicates = computed(() => report.value?.findings.filter(f => f.code === 'possible-duplicate') ?? [])
const otherFindings = computed(() => report.value?.findings.filter(f => f.code !== 'possible-duplicate') ?? [])

async function refreshOutputs() {
  report.value = null; reportNote.value = ''
  drafts.value = []; draftsNote.value = ''
  if (!rangeChosen.value) return
  const q = `since=${rangeSince.value}&until=${rangeUntil.value}`
  try {
    report.value = await apiFetch<Report>(`${BASE}/report?${q}`)
  } catch (e) {
    reportNote.value = e instanceof Error && e.message.startsWith('API 404')
      ? 'No validation report for this range yet. Run Validate.'
      : (e instanceof Error ? e.message : String(e))
  }
  try {
    drafts.value = await apiFetch<DraftRow[]>(`${BASE}/drafts?${q}`)
    if (!drafts.value.length) draftsNote.value = 'No drafts for this range yet.'
  } catch (e) {
    draftsNote.value = e instanceof Error && e.message.startsWith('API 404')
      ? 'Nothing built for this range yet. Run Build.'
      : (e instanceof Error ? e.message : String(e))
  }
}

function onSynthDone() {
  forceSynth.value = false
  refreshOutputs()
}

watch([rangeSince, rangeUntil], refreshOutputs)

onMounted(async () => {
  // useGroundingRun hydrates the refs on mount; give it a tick before reading.
  await (config.groundingConfig ?? config.refreshGrounding())
  setTimeout(() => { loadChapters(); refreshOutputs() }, 50)
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Summary-native</h2>
      <p class="subtitle">
        Build grounding-document drafts directly from reviewed session summaries &mdash; no extraction pass.
        Drafts are written for review; nothing here promotes one to the live document.
      </p>
    </div>

    <div class="form-grid">
      <!-- Input -->
      <div class="form-section">
        <PathField v-model="summariesDir" label="Summaries directory" required resolve-base="campaign"
          help="A directory of structured session summaries (*.md) whose filenames start with the chapter number." />
        <span v-if="chaptersError" class="field-error">{{ chaptersError }}</span>
      </div>

      <!-- Range -->
      <div class="form-section">
        <label class="field-label">Chapter range</label>
        <div v-if="chapters && chapters.present.length" class="range-row">
          <select class="field-input narrow" v-model="rangeSince" aria-label="First chapter">
            <option :value="null" disabled>first&hellip;</option>
            <option v-for="c in chapters.present" :key="c" :value="c">{{ c }}</option>
          </select>
          <span class="range-sep">to</span>
          <select class="field-input narrow" v-model="rangeUntil" aria-label="Last chapter">
            <option :value="null" disabled>last&hellip;</option>
            <option v-for="c in chapters.present" :key="c" :value="c">{{ c }}</option>
          </select>
          <button class="btn-neutral btn-sm" @click="selectAll">All chapters</button>
        </div>
        <span v-else class="field-help">
          {{ summariesDir.trim() ? 'No numbered summaries found in that directory.' : 'Set the summaries directory to list its chapters.' }}
        </span>
        <span v-if="chapters && chapters.duplicate_chapters.length" class="field-error">
          More than one file for chapter {{ chapters.duplicate_chapters.join(', ') }} &mdash; Validate will block until one is removed.
        </span>
        <span v-if="rangeInverted" class="field-error">The first chapter is after the last.</span>
        <span v-else-if="!rangeChosen" class="field-help">
          Choose a range explicitly. &ldquo;All chapters&rdquo; fills in the first and last chapter for you.
        </span>
      </div>

      <!-- 1. Validate -->
      <div class="form-section">
        <h3 class="step">1. Validate</h3>
        <div class="field">
          <label class="field-label">Possible-duplicate threshold</label>
          <input type="number" step="0.01" min="0" max="1" class="field-input narrow" v-model.number="dupThreshold" />
          <span class="field-help">Similarity ratio above which two entries are reported as possible duplicates. Blank uses the stored default.</span>
        </div>
        <RunPanel :endpoint="`${BASE}/run/validate`" :params="validateParams" :disabled="!ready"
          label="Validate" @done="refreshOutputs" />
      </div>

      <!-- 2. Build -->
      <div class="form-section">
        <h3 class="step">2. Build corpus</h3>
        <label class="checkbox-label">
          <input type="checkbox" v-model="forceBuild" /> Rebuild existing corpus (--force)
        </label>
        <RunPanel :endpoint="`${BASE}/run/build`" :params="buildParams" :disabled="!ready"
          label="Build" @done="refreshOutputs" />
      </div>

      <!-- 3. Synth -->
      <div class="form-section">
        <h3 class="step">3. Synthesize a draft</h3>
        <div class="field">
          <label class="field-label">Document</label>
          <select class="field-input narrow" v-model="doc">
            <option v-for="d in DOCS" :key="d" :value="d">{{ d }}</option>
          </select>
        </div>
        <PathField v-model="worldStatePath" label="World-state draft (context)" resolve-base="campaign"
          help="A GM-reviewed world_state draft to use as upstream context. Optional." />
        <PathField v-model="campaignStatePath" label="Campaign-state draft (context)" resolve-base="campaign"
          help="A GM-reviewed campaign_state draft to use as upstream context. Optional." />
        <div class="field">
          <label class="field-label">Audit files (campaign_state)</label>
          <textarea class="field-textarea" v-model="auditText" rows="3"
            placeholder="One path per line. Blank uses the Campaign State page's tracking lists." />
          <span class="field-help">Tracking, planning or module files treated as questions to answer from the summaries.</span>
        </div>
        <div class="field">
          <label class="field-label">Named subjects</label>
          <textarea class="field-textarea" v-model="namesText" rows="2"
            placeholder="One subject per line &mdash; force-includes these dossiers" />
        </div>
        <div class="num-grid">
          <div class="field">
            <label class="field-label">Recent chapters</label>
            <input type="number" min="0" class="field-input" v-model.number="recentChapters" />
            <span class="field-help">Counted back from the range end; 0 = all.</span>
          </div>
          <div class="field">
            <label class="field-label">Recurring minimum</label>
            <input type="number" min="0" class="field-input" v-model.number="recurringMin" />
            <span class="field-help">Observations that make an entity recurring.</span>
          </div>
          <div class="field">
            <label class="field-label">Parts</label>
            <input type="number" min="0" class="field-input" v-model.number="parts" />
            <span class="field-help">Split the outline into N calls; 0 = one call.</span>
          </div>
          <div class="field">
            <label class="field-label">Max tokens</label>
            <input type="number" min="1" class="field-input" v-model.number="maxTokens" />
            <span class="field-help">Per call. Blank uses the CLI default.</span>
          </div>
        </div>
        <label class="checkbox-label">
          <input type="checkbox" v-model="dumpOnly" /> Dump only &mdash; write the prompts and run record, make no model call
        </label>
        <label class="checkbox-label">
          <input type="checkbox" v-model="forceSynth" /> Replace existing reviewed draft (--force)
        </label>
        <RunPanel :endpoint="`${SYNTH_ENDPOINT}/${doc}`" :params="synthParams" :disabled="!ready"
          :label="`Synthesize ${doc}`" selection-service="grounding" selection-doc="summary_native"
          :selection-can-override="true" @done="onSynthDone" />
      </div>

      <!-- 4. Compare -->
      <div class="form-section">
        <h3 class="step">4. Compare with the live document</h3>
        <span class="field-help">Diffs the {{ doc }} draft against docs/{{ doc }}.md. Read-only.</span>
        <RunPanel :endpoint="`${BASE}/run/compare/${doc}`" :params="baseParams" :disabled="!ready"
          :label="`Compare ${doc}`" />
      </div>

      <!-- Report -->
      <div class="form-section">
        <h3 class="step">Validation report</h3>
        <span v-if="reportNote" class="field-help">{{ reportNote }}</span>
        <div v-if="report" class="panel">
          <div class="counts">
            <span>{{ report.files_in_range }} of {{ report.files_scanned }} files in range</span>
            <span :class="report.blocking_count ? 'bad' : 'ok'">{{ report.blocking_count }} blocking</span>
            <span>{{ report.non_blocking_count }} advisory</span>
            <span v-if="report.range.gaps.length">gaps: {{ report.range.gaps.join(', ') }}</span>
            <span v-if="report.existing_corpus">corpus: {{ report.existing_corpus.state }}</span>
          </div>
          <div v-if="duplicates.length" class="findings">
            <h4>Possible duplicates ({{ duplicates.length }})</h4>
            <p class="field-help">Review only. Rule on a pair in canon.yaml to silence it; nothing is merged for you.</p>
            <ul>
              <li v-for="(f, i) in duplicates" :key="'d' + i">
                <code>{{ f.file }}<template v-if="f.line">:{{ f.line }}</template></code> {{ f.message }}
              </li>
            </ul>
          </div>
          <div v-if="otherFindings.length" class="findings">
            <h4>Findings ({{ otherFindings.length }})</h4>
            <ul>
              <li v-for="(f, i) in otherFindings" :key="'f' + i" :class="{ bad: f.blocking }">
                <strong>{{ f.blocking ? 'BLOCK' : 'note' }}</strong>
                <code>{{ f.code }}</code>
                <code>{{ f.file }}<template v-if="f.line">:{{ f.line }}</template></code>
                {{ f.message }}
              </li>
            </ul>
          </div>
        </div>
      </div>

      <!-- Drafts -->
      <div class="form-section">
        <h3 class="step">Drafts</h3>
        <span v-if="draftsNote" class="field-help">{{ draftsNote }}</span>
        <table v-if="drafts.length" class="drafts">
          <thead><tr><th>Document</th><th>Status</th><th>Size</th><th>Path</th></tr></thead>
          <tbody>
            <tr v-for="d in drafts" :key="d.path">
              <td>{{ d.doc }}</td>
              <td :class="d.status === 'incomplete' ? 'bad' : 'ok'">{{ d.status }}</td>
              <td>{{ d.bytes }} B</td>
              <td><code>{{ d.path }}</code></td>
            </tr>
          </tbody>
        </table>
        <span v-if="drafts.length" class="field-help">
          An incomplete draft failed its outline check and is not promotable. Review a draft in your editor; promotion is manual.
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 1400px; height: 100%; overflow-y: auto; box-sizing: border-box; }
.page-header { margin-bottom: 20px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }

.form-grid { display: flex; flex-direction: column; gap: 16px; }
.form-section { padding-bottom: 12px; border-bottom: 1px solid var(--bg-surface0); }
.form-section:last-child { border-bottom: none; }
.step { font-size: 12px; font-weight: 700; color: var(--text); margin-bottom: 8px; }

.field { margin-bottom: 10px; }
.field-label { display: block; font-size: 11px; font-weight: 600; color: var(--text-sub); margin-bottom: 3px; }
.field-input, .field-textarea {
  width: 100%; padding: 6px 8px; border-radius: 4px;
  border: 1px solid var(--bg-surface1); background: var(--bg-base);
  color: var(--text); font-family: var(--mono); font-size: 11px;
  outline: none; box-sizing: border-box;
}
.field-input.narrow { width: 160px; }
.field-textarea { resize: vertical; }
.field-input:focus, .field-textarea:focus { border-color: var(--mauve); }
.field-help { display: block; font-size: 10px; color: var(--text-muted); margin-top: 3px; }
.field-error { display: block; font-size: 11px; color: var(--red); margin-top: 4px; }

.range-row { display: flex; align-items: center; gap: 8px; }
.range-sep { font-size: 11px; color: var(--text-muted); }
.num-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 0 16px; }

.checkbox-label { font-size: 11px; color: var(--text-sub); display: flex; align-items: center; gap: 6px; cursor: pointer; margin-bottom: 8px; }
.checkbox-label input { accent-color: var(--mauve); }

.panel { padding: 10px; background: var(--bg-mantle); border-radius: 4px; font-size: 11px; color: var(--text-sub); }
.counts { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 8px; }
.findings h4 { font-size: 11px; font-weight: 700; color: var(--text); margin: 8px 0 4px; }
.findings ul { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 3px; }
.findings code, .drafts code { font-family: var(--mono); font-size: 10px; margin-right: 6px; }
.ok { color: var(--green); }
.bad { color: var(--red); }

.drafts { border-collapse: collapse; font-size: 11px; color: var(--text-sub); margin-top: 6px; }
.drafts th, .drafts td { text-align: left; padding: 3px 14px 3px 0; }
.drafts th { font-weight: 600; color: var(--text); }
</style>
