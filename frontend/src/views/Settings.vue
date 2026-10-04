<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useConfigStore } from '../stores/config'
import { apiFetch, apiPost } from '../api/client'

const config = useConfigStore()

const resolvedJson = computed(() =>
  JSON.stringify(config.resolved, null, 2)
)

const trackedJson = computed(() =>
  JSON.stringify((config.values as any).tracked ?? {}, null, 2)
)

const localJson = computed(() =>
  JSON.stringify((config.values as any).local ?? {}, null, 2)
)

const configPath = computed(() => (config.values as any).config_path || '')
const localPath = computed(() => (config.values as any).local_config_path || '')
const sourceCheckout = ref('')
const wiringTarget = ref('')
const overwriteWiring = ref(false)
const migrationRunning = ref(false)
const migrationResult = ref('')

async function migrateWiring() {
  migrationResult.value = ''
  migrationRunning.value = true
  try {
    const result = await apiPost<{ returncode: number; output: string }>(
      '/api/config/wiring/migrate',
      {
        source_checkout: sourceCheckout.value,
        target: wiringTarget.value,
        force: overwriteWiring.value,
      },
    )
    migrationResult.value = `Exit ${result.returncode}\n${result.output}`
  } catch (error) {
    migrationResult.value = String(error)
  } finally {
    migrationRunning.value = false
  }
}

const lineCount = computed(() => {
  const lines = resolvedJson.value.split('\n').length
  return `${lines} line${lines === 1 ? '' : 's'}`
})

onMounted(async () => {
  // Migration-only startup intentionally serves no campaign configuration.
  if (!config.loaded) {
    try { await config.load() } catch { /* the migration form remains usable */ }
  }
  const wiring = await apiFetch<{ path: string }>('/api/config/wiring/default')
  wiringTarget.value = wiring.path
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Settings</h2>
      <p class="subtitle">
        Read-only view of the unified configuration. Edit
        <code>config.yaml</code> by hand for documents and prompt paths;
        edit per-page form fields for everything else.
      </p>
    </div>

    <div v-if="config.migrationWarnings.length" class="migration-banner">
      <strong>Migration notes</strong>
      <ul>
        <li v-for="(w, i) in config.migrationWarnings" :key="i">{{ w }}</li>
      </ul>
    </div>

    <div class="files">
      <div v-if="configPath" class="config-path">
        <span class="path-label">config.yaml</span>
        <code>{{ configPath }}</code>
      </div>
      <div v-if="localPath" class="config-path">
        <span class="path-label">.campaigngenerator.local.yaml</span>
        <code>{{ localPath }}</code>
      </div>
    </div>

    <section class="migration-panel">
      <h3>Move external wiring from an old checkout</h3>
      <p>Run this once before using an installed copy. The old file is removed only after the destination is written successfully. Update mneme's CampaignGenerator render target afterward.</p>
      <form @submit.prevent="migrateWiring">
        <label>Source checkout
          <input v-model="sourceCheckout" type="text" required placeholder="/absolute/path/to/CampaignGenerator" />
        </label>
        <label>Destination wiring file
          <input v-model="wiringTarget" type="text" required />
        </label>
        <label class="check"><input v-model="overwriteWiring" type="checkbox" /> Replace an existing destination</label>
        <button type="submit" :disabled="migrationRunning || !sourceCheckout.trim()">
          {{ migrationRunning ? 'Moving…' : 'Move wiring' }}
        </button>
      </form>
      <pre v-if="migrationResult" class="yaml-view" role="status">{{ migrationResult }}</pre>
    </section>

    <div class="editor-section">
      <div class="editor-toolbar">
        <span class="line-count">resolved · {{ lineCount }}</span>
      </div>

      <details open>
        <summary>resolved (typed view, paths absolute)</summary>
        <pre class="yaml-view">{{ resolvedJson }}</pre>
      </details>

      <details>
        <summary>tracked (config.yaml — human-edited)</summary>
        <pre class="yaml-view">{{ trackedJson }}</pre>
      </details>

      <details>
        <summary>local (.campaigngenerator.local.yaml — machine-only)</summary>
        <pre class="yaml-view">{{ localJson }}</pre>
      </details>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 900px; }
.page-header { margin-bottom: 16px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); line-height: 1.5; }
.subtitle code {
  font-family: var(--mono); color: var(--text-sub);
  background: var(--bg-surface0); padding: 1px 5px; border-radius: 3px;
  font-size: 11px;
}

.migration-banner {
  margin-bottom: 16px; padding: 10px 12px;
  background: #3a2e1e; color: var(--peach);
  border-radius: 4px; font-size: 11px; line-height: 1.5;
}
.migration-banner strong { display: block; margin-bottom: 4px; color: var(--yellow); }
.migration-banner ul { margin: 0; padding-left: 18px; }

.files { margin-bottom: 14px; display: flex; flex-direction: column; gap: 4px; }
.config-path { font-size: 11px; color: var(--text-muted); }
.path-label { font-weight: 600; margin-right: 6px; color: var(--text-sub); }
.config-path code {
  font-family: var(--mono); color: var(--text-sub);
  background: var(--bg-surface0); padding: 2px 6px; border-radius: 3px;
}

.editor-section { display: flex; flex-direction: column; gap: 10px; }
.migration-panel { margin-bottom: 18px; padding: 12px; border: 1px solid var(--bg-surface1); border-radius: 4px; }
.migration-panel h3 { margin: 0 0 6px; font-size: 13px; }
.migration-panel p { color: var(--text-muted); font-size: 11px; line-height: 1.5; }
.migration-panel form { display: flex; flex-direction: column; gap: 8px; }
.migration-panel label { display: flex; flex-direction: column; gap: 3px; font-size: 11px; }
.migration-panel label.check { flex-direction: row; align-items: center; }
.migration-panel input[type="text"] { padding: 5px; background: var(--bg-base); color: var(--text); border: 1px solid var(--bg-surface1); }
.migration-panel button { align-self: flex-start; padding: 5px 9px; }

.editor-toolbar {
  display: flex; align-items: center; justify-content: space-between;
}
.line-count { font-size: 10px; color: var(--text-muted); }

details > summary {
  cursor: pointer; font-size: 11px; font-weight: 600; color: var(--text-sub);
  padding: 6px 8px; background: var(--bg-mantle);
  border-radius: 4px;
}
details > summary:hover { color: var(--text); }

.yaml-view {
  margin: 6px 0 0;
  width: 100%; max-height: 480px; overflow: auto;
  padding: 10px 12px;
  border-radius: 4px; border: 1px solid var(--bg-surface1);
  background: var(--bg-base); color: var(--text);
  font-family: var(--mono); font-size: 11px; line-height: 1.6;
  box-sizing: border-box;
}
</style>
