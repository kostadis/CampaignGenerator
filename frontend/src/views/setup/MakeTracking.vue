<script setup lang="ts">
import { ref, computed } from 'vue'
import { useConfigStore } from '../../stores/config'
import PathField from '../../components/shared/PathField.vue'
import RunPanel from '../../components/shared/RunPanel.vue'

const config = useConfigStore()

// Deliberately stateless — see docs/config/ui-state-retirement.md D1. This
// page used to seed `output` from `ui.experimental.make_tracking.output`, a
// section nothing ever wrote (the generic PUT /section/{name} route had no
// client), so the read always returned {} and the literal default below was
// always what shipped. The GM's call: these are one-shot run forms, so the
// values stay in-component and reset on navigation rather than gaining a
// persistence tier of their own.
const input = ref('')
const output = ref('docs/tracking.txt')

const ready = computed(() =>
  !!(input.value.trim() && output.value.trim())
)

const runParams = computed(() => ({
  input: input.value,
  output: output.value,
  model: config.model,
}))
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Make Tracking List</h2>
      <p class="subtitle">Extract a tracking list from an adventure module so Campaign State never misses key events.</p>
    </div>

    <div class="form-grid">
      <div class="form-section">
        <PathField v-model="input" label="Adventure module file" required resolve-base="campaign"
          help="Adventure module or campaign markdown file." />
      </div>

      <div class="form-section">
        <PathField v-model="output" label="Output file" required is-output resolve-base="campaign"
          help="tracking.txt — feed this to Campaign State via --track-file." />
      </div>

      <div class="info-box">
        Review and edit the generated tracking list before using it with Campaign State.
        Items are phrased neutrally — verify they match your campaign's actual events.
      </div>

      <RunPanel
        selection-service="setup"
        endpoint="/api/setup/run/make-tracking"
        :params="runParams"
        :disabled="!ready"
        label="Extract Tracking List"
        @done="() => {}"
      />
    </div>
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 700px; }
.page-header { margin-bottom: 20px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }

.form-grid { display: flex; flex-direction: column; gap: 16px; }
.form-section {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--bg-surface0);
}
.form-section:last-child { border-bottom: none; }

.info-box {
  padding: 10px 14px; background: #1e3a5f; border-radius: 4px;
  font-size: 11px; color: var(--blue); line-height: 1.5;
}
</style>
