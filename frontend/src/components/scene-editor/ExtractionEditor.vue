<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { apiFetch } from '../../api/client'

const REVIEW_BANNER_KEY = 'cg_scene_review_banner_dismissed'

const props = defineProps<{
  extractionContent: string
  enhancedContent: string
  sceneLabel: string
  estimatedTokens: number | null
  defaultNarrateTokens: number
  hasExtraction: boolean
  hasEnhanced: boolean
  narrating: boolean
  extracting: boolean
  proseMode: boolean
  reflections: boolean
  useEnhancedSections: boolean
  reviewed: boolean
  currentScene: number | null
}>()

const emit = defineEmits<{
  'save-extraction': [content: string]
  'reload': []
  'narrate': []
  'open-typora': [type: string]
  'update:extractionContent': [content: string]
  'update:proseMode': [value: boolean]
  'update:reflections': [value: boolean]
  'update:useEnhancedSections': [value: boolean]
  'update:reviewed': [value: boolean]
  'load-enhanced': []
}>()

const activeTab = ref<'extraction' | 'enhanced'>('extraction')
const saveFlash = ref(false)
const reviewBannerDismissed = ref(false)

onMounted(() => {
  reviewBannerDismissed.value = localStorage.getItem(REVIEW_BANNER_KEY) === '1'
})

function dismissReviewBanner() {
  reviewBannerDismissed.value = true
  localStorage.setItem(REVIEW_BANNER_KEY, '1')
}

const showReviewBanner = computed(() =>
  activeTab.value === 'extraction'
    && props.hasExtraction
    && !reviewBannerDismissed.value
)

// Token estimate
function estimateTokens(text: string): number {
  const lines = text.split('\n')
  let content = text
  if (lines[0]?.trim().match(/^tokens:\s*\d+/)) {
    content = lines.slice(1).join('\n')
  }
  const hasDlg = /^[A-Z][^:\n]+:\s*"/m.test(content)
  const raw = Math.floor(content.length / 4 * (hasDlg ? 4 : 3))
  return Math.max(500, Math.ceil(raw / 250) * 250)
}

const tokenEst = computed(() => {
  if (activeTab.value !== 'extraction' || !props.extractionContent.trim()) return null
  return estimateTokens(props.extractionContent)
})

const tokenWarn = computed(() => {
  return tokenEst.value !== null && tokenEst.value > props.defaultNarrateTokens
})

function flash() {
  saveFlash.value = true
  setTimeout(() => { saveFlash.value = false }, 1800)
}

function save() {
  if (activeTab.value === 'extraction') {
    emit('save-extraction', props.extractionContent)
  }
  flash()
}

function openTypora() {
  emit('open-typora', 'extraction')
}

// ── Diff vs. last run ───────────────────────────────────────────────────
// Lazy-loaded via /api/editor/extraction/{n}/prev. .prev is created by
// scene_extract.py --force when a re-run produces content that differs
// from what's already on disk.

type DiffLine = { kind: 'eq' | 'add' | 'del'; text: string }

const diffMode = ref(false)
const diffStatus = ref<'idle' | 'loading' | 'none' | 'ready'>('idle')
const diffLines = ref<DiffLine[]>([])

// Reset diff state whenever the user moves to another scene.
watch(() => props.currentScene, () => {
  diffMode.value = false
  diffStatus.value = 'idle'
  diffLines.value = []
})

function lineDiff(prev: string, curr: string): DiffLine[] {
  const a = prev.split('\n')
  const b = curr.split('\n')
  const m = a.length
  const n = b.length
  // LCS table — O(m*n) memory; fine for scene-extraction sizes (<2k lines).
  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    }
  }
  const out: DiffLine[] = []
  let i = 0
  let j = 0
  while (i < m && j < n) {
    if (a[i] === b[j]) {
      out.push({ kind: 'eq', text: a[i] })
      i++
      j++
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      out.push({ kind: 'del', text: a[i] })
      i++
    } else {
      out.push({ kind: 'add', text: b[j] })
      j++
    }
  }
  while (i < m) { out.push({ kind: 'del', text: a[i] }); i++ }
  while (j < n) { out.push({ kind: 'add', text: b[j] }); j++ }
  return out
}

async function toggleDiff() {
  if (diffMode.value) {
    diffMode.value = false
    return
  }
  if (!props.currentScene) return
  diffMode.value = true
  diffStatus.value = 'loading'
  try {
    const data = await apiFetch<{ exists: boolean; content: string; current?: string }>(
      `/api/editor/extraction/${props.currentScene}/prev`
    )
    if (!data.exists) {
      diffStatus.value = 'none'
      diffLines.value = []
      return
    }
    diffLines.value = lineDiff(data.content, data.current ?? props.extractionContent)
    diffStatus.value = 'ready'
  } catch {
    diffStatus.value = 'none'
    diffLines.value = []
  }
}
</script>

<template>
  <div class="editor-col">
    <!-- Header -->
    <div class="editor-header">
      <span class="editor-title">{{ sceneLabel || 'Select a scene' }}</span>
      <span
        v-if="tokenEst !== null"
        class="token-est"
        :class="{ 'token-warn': tokenWarn }"
      >
        ~{{ tokenEst }} tokens
        <template v-if="tokenWarn"> &#x26A0; limit {{ defaultNarrateTokens }}</template>
      </span>
    </div>

    <!-- Tabs -->
    <div class="tab-bar">
      <div
        class="tab"
        :class="{ active: activeTab === 'extraction' }"
        @click="activeTab = 'extraction'"
      >Extraction</div>
      <div
        class="tab"
        :class="{ active: activeTab === 'enhanced' }"
        @click="activeTab = 'enhanced'; emit('load-enhanced')"
      >
        Session Notes
        <span v-if="hasEnhanced" class="tab-badge">ready</span>
      </div>
    </div>

    <!-- Extraction pane -->
    <div class="editor-pane" :class="{ hidden: activeTab !== 'extraction' }">
      <div v-if="showReviewBanner" class="review-banner">
        <div class="review-banner-text">
          <strong>Confirm the order is right.</strong>
          You only need to edit if something is wrong — the LLM will
          render in the order it sees and will not reorder events.
          Edit for: stray lines from another scene, hallucinated quotes,
          interleaved exchanges that should be tightened, missing GM beats.
          A "no edits needed" review is a valid outcome.
        </div>
        <button
          type="button"
          class="review-banner-dismiss"
          @click="dismissReviewBanner"
          title="Got it — don't show again"
        >&times;</button>
      </div>
      <textarea
        v-if="!diffMode"
        class="editor-ta"
        :value="extractionContent"
        @input="emit('update:extractionContent', ($event.target as HTMLTextAreaElement).value)"
        :disabled="!hasExtraction"
        placeholder="Select a scene from the list to begin editing."
        spellcheck="false"
      />
      <div v-else class="diff-pane">
        <div v-if="diffStatus === 'loading'" class="diff-info">Loading prior version&hellip;</div>
        <div v-else-if="diffStatus === 'none'" class="diff-info">
          No prior version recorded for this scene. A <code>.prev</code> file
          is written only when a re-run with <em>force</em> produces content
          that differs from what's already on disk.
        </div>
        <div v-else class="diff-body">
          <div
            v-for="(line, idx) in diffLines"
            :key="idx"
            class="diff-line"
            :class="'diff-' + line.kind"
          >
            <span class="diff-marker">{{ line.kind === 'add' ? '+' : line.kind === 'del' ? '-' : ' ' }}</span>
            <span class="diff-text">{{ line.text }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Enhanced / Session Notes pane (read-only) -->
    <div class="editor-pane" :class="{ hidden: activeTab !== 'enhanced' }">
      <textarea
        class="editor-ta"
        :value="enhancedContent"
        readonly
        placeholder="No enhanced_sections.md found. Run Scene Extraction first."
        spellcheck="false"
      />
    </div>

    <!-- Toolbar -->
    <div class="toolbar">
      <button class="btn-primary" :disabled="!hasExtraction || activeTab === 'enhanced'" @click="save">Save</button>
      <button class="btn-neutral" :disabled="!hasExtraction || activeTab === 'enhanced'" @click="openTypora">Edit in Typora</button>
      <button class="btn-neutral" :disabled="!hasExtraction" @click="emit('reload')">Reload</button>
      <button
        class="btn-neutral"
        :disabled="!hasExtraction || activeTab !== 'extraction' || !currentScene"
        :class="{ active: diffMode }"
        @click="toggleDiff"
        title="Diff this scene's extraction against the prior version (.prev) saved on the last force re-run"
      >{{ diffMode ? 'Hide diff' : 'Diff vs. last run' }}</button>
      <button
        class="btn-success"
        :disabled="!hasExtraction || narrating || extracting"
        @click="emit('narrate')"
      >{{ narrating ? 'Narrating\u2026' : 'Narrate' }}</button>
      <label class="prose-toggle" :title="'Strip mechanical language and GM framing from narration'">
        <input type="checkbox" :checked="proseMode"
          @change="emit('update:proseMode', ($event.target as HTMLInputElement).checked)" />
        Prose
      </label>
      <label class="prose-toggle" :title="'Inject campaign history so the narrator can draw on past events as memories and reflections'">
        <input type="checkbox" :checked="reflections"
          @change="emit('update:reflections', ($event.target as HTMLInputElement).checked)" />
        Memories
      </label>
      <label class="prose-toggle" :title="'Pass enhanced_sections.md to the narration as scene context'">
        <input type="checkbox" :checked="useEnhancedSections"
          @change="emit('update:useEnhancedSections', ($event.target as HTMLInputElement).checked)" />
        Enhanced
      </label>
      <label class="prose-toggle reviewed-toggle"
             :class="{ on: reviewed }"
             title="Mark this scene's extraction order as reviewed">
        <input type="checkbox" :checked="reviewed"
          :disabled="!hasExtraction"
          @change="emit('update:reviewed', ($event.target as HTMLInputElement).checked)" />
        Reviewed
      </label>
      <span class="save-flash" :class="{ show: saveFlash }">Saved</span>
      <span style="flex:1"></span>
      <button class="btn-neutral btn-sm" :disabled="!hasExtraction" @click="emit('open-typora', 'output')">
        Open narration in Typora
      </button>
    </div>
  </div>
</template>

<style scoped>
.editor-col {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex: 1;
}

.editor-header {
  background: var(--bg-mantle);
  border-bottom: 1px solid var(--bg-surface0);
  padding: 7px 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.editor-title {
  font-size: 13px;
  font-weight: 600;
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.token-est { font-size: 11px; color: var(--text-muted); white-space: nowrap; flex-shrink: 0; }
.token-warn { color: var(--peach) !important; }

.tab-bar {
  background: var(--bg-mantle);
  border-bottom: 1px solid var(--bg-surface0);
  display: flex;
  flex-shrink: 0;
}
.tab {
  padding: 6px 14px;
  font-size: 11px;
  font-weight: 600;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  color: var(--text-muted);
  transition: color .1s;
}
.tab:hover { color: var(--text); }
.tab.active { color: var(--mauve); border-bottom-color: var(--mauve); }
.tab-badge {
  display: inline-block;
  font-size: 9px;
  font-weight: 700;
  padding: 1px 4px;
  border-radius: 3px;
  margin-left: 4px;
  background: #1e3a2a;
  color: var(--green);
  text-transform: uppercase;
  letter-spacing: .04em;
}

.editor-pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.editor-pane.hidden { display: none; }

.editor-ta {
  flex: 1;
  background: var(--bg-base);
  color: var(--text);
  border: none;
  outline: none;
  resize: none;
  padding: 12px 14px;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.65;
}

.toolbar {
  background: var(--bg-mantle);
  border-top: 1px solid var(--bg-surface0);
  padding: 7px 12px;
  display: flex;
  gap: 6px;
  align-items: center;
  flex-shrink: 0;
}
.save-flash {
  font-size: 11px;
  color: var(--green);
  opacity: 0;
  transition: opacity .4s;
}
.save-flash.show { opacity: 1; }
.prose-toggle {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: var(--text-muted);
  cursor: pointer;
  user-select: none;
}
.prose-toggle input { cursor: pointer; }
.prose-toggle.reviewed-toggle.on { color: #a6d189; font-weight: 600; }

.review-banner {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 8px 12px;
  background: rgba(245, 169, 127, 0.08);
  border-bottom: 1px solid var(--bg-surface0);
  border-left: 3px solid var(--peach);
  flex-shrink: 0;
}
.review-banner-text {
  flex: 1;
  font-size: 11px;
  line-height: 1.5;
  color: var(--text-sub);
}
.review-banner-text strong { color: var(--text); font-weight: 700; }
.review-banner-dismiss {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  padding: 0 4px;
  flex-shrink: 0;
}
.review-banner-dismiss:hover { color: var(--text); }

.diff-pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--bg-base);
}
.diff-info {
  padding: 14px;
  font-size: 12px;
  color: var(--text-muted);
  line-height: 1.5;
}
.diff-info code { background: var(--bg-mantle); padding: 1px 4px; border-radius: 3px; }
.diff-body {
  flex: 1;
  overflow: auto;
  padding: 8px 0;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.5;
}
.diff-line {
  display: flex;
  padding: 0 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
.diff-line.diff-eq { color: var(--text-sub); }
.diff-line.diff-add { background: rgba(166, 209, 137, 0.10); color: #a6d189; }
.diff-line.diff-del { background: rgba(231, 130, 132, 0.10); color: #e78284; }
.diff-marker {
  width: 16px;
  flex-shrink: 0;
  user-select: none;
  opacity: 0.7;
}
.diff-text { flex: 1; }
.btn-neutral.active { background: var(--mauve); color: var(--bg-base); }
</style>
