<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { apiFetch, apiPut } from '../api/client'

const yamlText = ref('')
const configPath = ref('')
const saved = ref(false)
const error = ref('')
const loading = ref(true)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data: any = await apiFetch('/api/config/raw')
    yamlText.value = data.text || ''
    configPath.value = data.path || ''
  } catch (e: any) {
    error.value = `Failed to load: ${e.message}`
  } finally {
    loading.value = false
  }
}

async function save() {
  saved.value = false
  error.value = ''
  try {
    const res: any = await apiPut('/api/config/raw', { text: yamlText.value })
    if (res.ok) {
      saved.value = true
      setTimeout(() => { saved.value = false }, 3000)
    } else {
      error.value = `Invalid YAML: ${res.error}`
    }
  } catch (e: any) {
    error.value = `Save failed: ${e.message}`
  }
}

const lineCount = computed(() => {
  const lines = yamlText.value.split('\n').length
  return `${lines} line${lines === 1 ? '' : 's'}`
})

onMounted(() => { load() })
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Settings</h2>
      <p class="subtitle">View and edit your UI configuration file.</p>
    </div>

    <div class="config-path" v-if="configPath">
      <span class="path-label">Config file:</span>
      <code>{{ configPath }}</code>
    </div>

    <div v-if="loading" class="loading">Loading config...</div>

    <div v-else class="editor-section">
      <div class="editor-toolbar">
        <span class="line-count">{{ lineCount }}</span>
        <div class="toolbar-actions">
          <button class="btn-neutral btn-sm" @click="load">Reload</button>
          <button class="btn-primary btn-sm" @click="save">Save</button>
        </div>
      </div>

      <textarea
        class="yaml-editor"
        v-model="yamlText"
        spellcheck="false"
        autocomplete="off"
        autocorrect="off"
        autocapitalize="off"
      />

      <div v-if="saved" class="status-msg success">
        Saved. Config changes take effect on the next page that reads them.
      </div>
      <div v-if="error" class="status-msg error">
        {{ error }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 800px; }
.page-header { margin-bottom: 16px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }

.config-path {
  margin-bottom: 12px; font-size: 11px; color: var(--text-muted);
}
.path-label { font-weight: 600; margin-right: 6px; }
.config-path code {
  font-family: var(--mono); color: var(--text-sub);
  background: var(--bg-surface0); padding: 2px 6px; border-radius: 3px;
}

.loading { font-size: 12px; color: var(--text-muted); padding: 20px 0; }

.editor-section { display: flex; flex-direction: column; gap: 8px; }

.editor-toolbar {
  display: flex; align-items: center; justify-content: space-between;
}
.line-count { font-size: 10px; color: var(--text-muted); }
.toolbar-actions { display: flex; gap: 8px; }

.yaml-editor {
  width: 100%; min-height: 420px; padding: 10px 12px;
  border-radius: 4px; border: 1px solid var(--bg-surface1);
  background: var(--bg-base); color: var(--text);
  font-family: var(--mono); font-size: 11px; line-height: 1.6;
  outline: none; resize: vertical; box-sizing: border-box;
  tab-size: 2;
}
.yaml-editor:focus { border-color: var(--mauve); }

.status-msg {
  padding: 8px 12px; border-radius: 4px;
  font-size: 11px; line-height: 1.4;
}
.status-msg.success { background: #1e3a2a; color: var(--green); }
.status-msg.error { background: #3a1e1e; color: var(--red); }
</style>
