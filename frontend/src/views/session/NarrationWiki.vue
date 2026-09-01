<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import ConflictRulingCard from '../../components/narration-wiki/ConflictRulingCard.vue'
import MeasurementTable from '../../components/narration-wiki/MeasurementTable.vue'
import PatternGateCard from '../../components/narration-wiki/PatternGateCard.vue'
import ProposalGatePanel from '../../components/narration-wiki/ProposalGatePanel.vue'
import { fetchWikiStatus, runWikiAction, type WikiScope, type WikiStatus } from '../../api/narrationWiki'
import { useConfigStore } from '../../stores/config'

const config = useConfigStore()
const campaignId = ref('')
const sessionRelative = ref('')
const iterationId = ref('iter-001')
const status = ref<WikiStatus | null>(null)
const loadingStatus = ref(false)
const running = ref(false)
const output = ref('')
const command = ref('')
const error = ref('')
const stagedDiff = ref('')
let controller: AbortController | null = null

const scope = computed<WikiScope>(() => ({
  campaign_id: campaignId.value.trim(),
  session_relative: sessionRelative.value.trim(),
  iteration_id: iterationId.value.trim(),
}))
const scopeReady = computed(() => Object.values(scope.value).every(Boolean))
const firstConflict = computed(() => status.value?.unresolved_conflict_ids[0] ?? null)

function basename(path: string): string {
  return path.replace(/[\\/]+$/, '').split(/[\\/]/).pop() ?? ''
}

function initialSelection() {
  const campaign = String(config.resolved?.campaign_dir ?? config.editorConfig?.campaign_dir ?? '')
  const session = String(config.resolved?.runtime?.session_dir ?? config.editorConfig?.session_dir ?? '')
  campaignId.value ||= String(config.values?.campaign_id ?? basename(campaign))
  if (!sessionRelative.value && campaign && session) {
    const normalizedCampaign = campaign.replace(/\\/g, '/').replace(/\/$/, '')
    const normalizedSession = session.replace(/\\/g, '/')
    sessionRelative.value = normalizedSession.startsWith(`${normalizedCampaign}/`)
      ? normalizedSession.slice(normalizedCampaign.length + 1)
      : ''
  }
}

async function reloadStatus() {
  if (!scopeReady.value) return
  loadingStatus.value = true
  try {
    status.value = await fetchWikiStatus(scope.value)
    error.value = ''
  } catch (reason) {
    status.value = null
    error.value = reason instanceof Error ? reason.message : String(reason)
  } finally {
    loadingStatus.value = false
  }
}

async function run(action: Parameters<typeof runWikiAction>[0], fields: Record<string, unknown> = {}) {
  if (!scopeReady.value || running.value) return
  running.value = true
  output.value = ''
  command.value = ''
  error.value = ''
  controller = new AbortController()
  try {
    await runWikiAction(action, { ...scope.value, ...fields }, {
      onCommand(value) { command.value = value },
      onData(value) { output.value += value },
      onDone(returncode, detail) {
        if (returncode !== 0) error.value = detail ?? `Command exited with category ${returncode}`
      },
      onError(reason) { error.value = reason.message },
    }, controller.signal)
  } catch (reason) {
    if (!(reason instanceof DOMException && reason.name === 'AbortError')) {
      error.value = reason instanceof Error ? reason.message : String(reason)
    }
  } finally {
    running.value = false
    controller = null
    await reloadStatus()
  }
}

function cancel() {
  controller?.abort()
}

onMounted(async () => {
  await config.load()
  initialSelection()
  await reloadStatus()
})
onBeforeUnmount(cancel)
</script>

<template>
  <main class="narration-wiki-page">
    <header class="page-header">
      <div><h2>Narration Wiki</h2><p>Collect evidence, review durable lessons, and decide each guidance change at two human Gates.</p></div>
      <div class="header-actions">
        <button class="btn-neutral" :disabled="!scopeReady || loadingStatus || running" @click="reloadStatus">Reload status</button>
        <button class="btn-neutral" :disabled="!running" @click="cancel">Cancel running action</button>
      </div>
    </header>

    <section class="selection wiki-panel" aria-labelledby="selection-heading">
      <h3 id="selection-heading">Explicit selected session</h3>
      <div class="selection-grid">
        <label>Campaign ID<input v-model="campaignId" type="text" /></label>
        <label>Session relative path<input v-model="sessionRelative" type="text" /></label>
        <label>Iteration ID<input v-model="iterationId" type="text" /></label>
      </div>
    </section>

    <div v-if="error" class="error-banner" role="alert">{{ error }}</div>

    <section class="wiki-panel" aria-labelledby="status-heading">
      <h3 id="status-heading">Disk-derived state</h3>
      <div class="wiki-resizable-panel status-grid" tabindex="0">
        <template v-if="status">
          <span>State</span><strong>{{ status.state }}</strong>
          <span>Corpus</span><code>{{ status.corpus_id ?? 'not collected' }}</code>
          <span>Patterns</span><code>{{ status.pattern_counts }}</code>
          <span>Active proposal</span><code>{{ status.active_proposal_id ?? 'none' }}</code>
          <span>Recovery</span><code>{{ status.recovery ?? 'none' }}</code>
        </template>
        <p v-else>{{ loadingStatus ? 'Loading…' : 'Select one existing session and reload.' }}</p>
      </div>
    </section>

    <section class="wiki-panel" aria-labelledby="dependency-heading">
      <h3 id="dependency-heading">Companion dependency</h3>
      <div class="wiki-resizable-panel dependency-grid" tabindex="0">
        <template v-if="status?.dependency">
          <span>Present</span><strong>{{ status.dependency.present }}</strong>
          <span>Compatible</span><strong>{{ status.dependency.compatible }}</strong>
          <span>Repository</span><code>{{ status.dependency.source_repository ?? 'unavailable' }}</code>
          <span>Revision</span><code>{{ status.dependency.source_revision ?? 'unavailable' }}</code>
          <span>Roles</span><code>{{ status.dependency.capabilities.join(', ') || 'unavailable' }}</code>
          <span>Reason</span><span>{{ status.dependency.reason ?? 'ready' }}</span>
        </template>
      </div>
    </section>

    <section class="workflow-actions wiki-panel" aria-labelledby="evidence-heading">
      <h3 id="evidence-heading">Evidence and audit actions</h3>
      <div class="action-row">
        <button class="btn-primary" :disabled="!scopeReady || running" @click="run('collect')">Collect</button>
        <button class="btn-primary" :disabled="!scopeReady || running" @click="run('measure', { phase: 'before', proposal_id: null })">Measure baseline</button>
        <button class="btn-neutral" :disabled="!scopeReady || running" @click="run('index-check')">Check indexes</button>
        <button class="btn-primary" :disabled="!scopeReady || running || !status?.active_proposal_id"
          @click="run('measure', { phase: 'after', proposal_id: status?.active_proposal_id })">Measure comparison</button>
      </div>
    </section>

    <MeasurementTable :checks="status?.measurement_checks ?? []" />
    <ConflictRulingCard :conflict-id="firstConflict" :disabled="running" @rule="run('conflict-rule', $event)" />
    <PatternGateCard :disabled="running" @rule="run('pattern-rule', $event)" />
    <ProposalGatePanel
      :active-proposal-id="status?.active_proposal_id ?? null"
      :diff="stagedDiff"
      :disabled="running"
      @stage="run('proposal-stage', { ...$event, evidence_bindings: [] })"
      @apply="run('proposal-apply', { proposal_id: $event })"
      @rule="run('proposal-rule', $event)"
    />

    <section class="wiki-panel" aria-labelledby="output-heading">
      <h3 id="output-heading">Streamed output and history</h3>
      <div class="wiki-resizable-panel output-panel" tabindex="0">
        <code v-if="command">$ {{ command }}</code>
        <pre>{{ output || 'No command output yet.' }}</pre>
      </div>
    </section>
  </main>
</template>

<style scoped>
.narration-wiki-page { height: 100%; min-width: 0; overflow: auto; padding: 18px 22px 36px; }
.page-header { display: flex; justify-content: space-between; gap: 16px; min-width: 720px; margin-bottom: 14px; }
.page-header h2 { font-size: 17px; }
.page-header p { margin-top: 4px; color: var(--text-muted); font-size: 11px; }
.header-actions, .action-row { display: flex; align-items: flex-start; gap: 8px; min-width: max-content; }
.wiki-panel { min-width: 700px; margin-bottom: 14px; padding: 12px; border: 1px solid var(--bg-surface1); border-radius: 6px; background: var(--bg-mantle); }
.wiki-panel h3 { font-size: 12px; margin-bottom: 8px; }
.selection-grid { display: grid; grid-template-columns: minmax(180px, 1fr) minmax(300px, 2fr) minmax(160px, 1fr); gap: 10px; min-width: 720px; }
label { color: var(--text-sub); font-size: 10px; }
input { display: block; width: 100%; margin-top: 4px; padding: 6px 8px; border: 1px solid var(--bg-surface1); border-radius: 4px; background: var(--bg-base); color: var(--text); font: 11px var(--mono); }
.status-grid, .dependency-grid { display: grid; grid-template-columns: 150px minmax(520px, 1fr); gap: 7px 12px; font-size: 11px; }
.status-grid code, .dependency-grid code { white-space: nowrap; font-family: var(--mono); color: var(--teal); }
.error-banner { min-width: 700px; margin-bottom: 12px; padding: 9px 11px; border: 1px solid var(--red); border-radius: 4px; color: var(--red); background: var(--bg-mantle); font-size: 11px; }
.output-panel code { display: block; min-width: max-content; margin-bottom: 8px; color: var(--teal); font: 11px var(--mono); }
.output-panel pre { min-width: max-content; white-space: pre; font: 11px/1.45 var(--mono); color: var(--text-sub); }
</style>
