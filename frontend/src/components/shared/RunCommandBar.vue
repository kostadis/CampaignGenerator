<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ command: string }>()

const copied = ref(false)

function copy() {
  if (!props.command) return
  navigator.clipboard.writeText(props.command).then(() => {
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  })
}
</script>

<template>
  <div v-if="command" class="command-bar">
    <span class="label">Command</span>
    <pre class="command-text">{{ command }}</pre>
    <button class="copy-btn" :class="{ copied }" @click="copy" title="Copy to clipboard">
      {{ copied ? 'Copied!' : 'Copy' }}
    </button>
  </div>
  <div v-else class="command-bar command-bar--empty">
    <span class="label">Command</span>
    <span class="placeholder">Run a stage to see the exact command.</span>
  </div>
</template>

<style scoped>
.command-bar {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  background: var(--bg-surface0);
  border: 1px solid var(--bg-surface1);
  border-radius: 4px;
  padding: 8px 10px;
  margin-bottom: 10px;
  font-size: 11px;
}
.command-bar--empty { opacity: 0.55; }
.label {
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  white-space: nowrap;
  padding-top: 1px;
  min-width: 58px;
}
.command-text {
  flex: 1;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text);
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
}
.placeholder { flex: 1; color: var(--text-muted); font-style: italic; }
.copy-btn {
  flex-shrink: 0;
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 3px;
  border: 1px solid var(--bg-surface1);
  background: var(--bg-mantle);
  color: var(--text-muted);
  cursor: pointer;
  transition: background 0.1s, color 0.1s;
}
.copy-btn:hover { background: var(--bg-surface1); color: var(--text); }
.copy-btn.copied { background: var(--green); color: var(--bg-mantle); border-color: var(--green); }
</style>
