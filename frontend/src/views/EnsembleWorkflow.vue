<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { watch } from 'vue'
import WizardShell from '../components/wizard/WizardShell.vue'
import type { WizardStep } from '../components/wizard/WizardShell.vue'
import { apiFetch } from '../api/client'

const steps: WizardStep[] = [
  { number: 1, label: 'Setup', path: '/ensemble/setup' },
  { number: 2, label: 'Extract', path: '/ensemble/extract' },
  { number: 3, label: 'Bundle', path: '/ensemble/bundle' },
  { number: 4, label: 'Synthesize', path: '/ensemble/synthesize' },
]

// Disk-derived stage status (FR-002). Recomputed on mount and on navigation, so
// it reflects work done from the CLI/chat and survives reload — never cached in
// the browser.
const stages = ref<any[]>([])
const currentStage = ref('')
const route = useRoute()

async function loadStatus() {
  try {
    const s = await apiFetch('/api/ensemble/status')
    stages.value = s.stages ?? []
    currentStage.value = s.current_stage ?? ''
  } catch {
    stages.value = []
  }
}

onMounted(loadStatus)
watch(() => route.path, loadStatus)
</script>

<template>
  <WizardShell :steps="steps">
    <div class="ensemble-status">
      <span class="status-label">PIPELINE STATE (from disk):</span>
      <span
        v-for="s in stages"
        :key="s.id"
        class="status-chip"
        :class="{ complete: s.status === 'complete', current: s.id === currentStage }"
      >{{ s.id }}: {{ s.status === 'complete' ? '✓' : '—' }}</span>
      <button class="btn-neutral btn-sm refresh" @click="loadStatus">↻</button>
    </div>
    <router-view @changed="loadStatus" />
  </WizardShell>
</template>

<style scoped>
.ensemble-status {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 8px 14px;
  background: var(--bg-mantle);
  border-bottom: 1px solid var(--bg-surface0);
  font-size: 11px;
}
.status-label { font-weight: 700; color: var(--text-muted); letter-spacing: .04em; }
.status-chip {
  font-family: var(--mono);
  padding: 2px 8px;
  border-radius: 10px;
  background: var(--bg-surface0);
  color: var(--text-muted);
}
.status-chip.complete { color: var(--green); }
.status-chip.current { border: 1px solid var(--mauve); color: var(--text); }
.refresh { margin-left: auto; }
</style>
