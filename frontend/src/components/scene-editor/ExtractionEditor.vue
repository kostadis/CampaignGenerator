<script setup lang="ts">
import { ref, computed } from 'vue'

const props = defineProps<{
  extractionContent: string
  roleplayContent: string
  sceneLabel: string
  estimatedTokens: number | null
  defaultNarrateTokens: number
  hasExtraction: boolean
  isRoleplayLocal: boolean
  narrating: boolean
  extracting: boolean
  proseMode: boolean
}>()

const emit = defineEmits<{
  'save-extraction': [content: string]
  'save-roleplay': [content: string]
  'reload': []
  'narrate': []
  'open-typora': [type: string]
  'update:extractionContent': [content: string]
  'update:roleplayContent': [content: string]
  'update:proseMode': [value: boolean]
}>()

const activeTab = ref<'extraction' | 'roleplay'>('extraction')
const saveFlash = ref(false)

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
  if (activeTab.value === 'roleplay') {
    emit('save-roleplay', props.roleplayContent)
  } else {
    emit('save-extraction', props.extractionContent)
  }
  flash()
}

function openTypora() {
  const type = activeTab.value === 'roleplay' ? 'roleplay' : 'extraction'
  emit('open-typora', type)
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
        :class="{ active: activeTab === 'roleplay' }"
        @click="activeTab = 'roleplay'"
      >
        Roleplay Context
        <span v-if="isRoleplayLocal" class="tab-badge">edited</span>
      </div>
    </div>

    <!-- Extraction pane -->
    <div class="editor-pane" :class="{ hidden: activeTab !== 'extraction' }">
      <textarea
        class="editor-ta"
        :value="extractionContent"
        @input="emit('update:extractionContent', ($event.target as HTMLTextAreaElement).value)"
        :disabled="!hasExtraction"
        placeholder="Select a scene from the list to begin editing."
        spellcheck="false"
      />
    </div>

    <!-- Roleplay pane -->
    <div class="editor-pane" :class="{ hidden: activeTab !== 'roleplay' }">
      <textarea
        class="editor-ta"
        :value="roleplayContent"
        @input="emit('update:roleplayContent', ($event.target as HTMLTextAreaElement).value)"
        placeholder="No roleplay summary loaded."
        spellcheck="false"
      />
    </div>

    <!-- Toolbar -->
    <div class="toolbar">
      <button class="btn-primary" :disabled="!hasExtraction" @click="save">Save</button>
      <button class="btn-neutral" :disabled="!hasExtraction" @click="openTypora">Edit in Typora</button>
      <button class="btn-neutral" :disabled="!hasExtraction" @click="emit('reload')">Reload</button>
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
</style>
