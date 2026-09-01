<script setup lang="ts">
import { computed } from 'vue'
import type { MeasurementCheck } from '../../api/narrationWiki'

const props = defineProps<{ checks: MeasurementCheck[]; phase?: 'before' | 'after' | null }>()

// Naming the phase keeps the table honest: after a proposal is applied these
// rows are the comparison, not the baseline they are read against.
const phaseLabel = computed(() =>
  props.phase === 'after' ? ' — comparison' : props.phase === 'before' ? ' — baseline' : '',
)

function budget(check: MeasurementCheck): string {
  return check.budget
    ? `${check.budget.operator} ${check.budget.value} ${check.budget.unit}`
    : 'unconfigured'
}
</script>

<template>
  <section class="wiki-panel" aria-labelledby="measurement-heading">
    <h3 id="measurement-heading">Measurement evidence{{ phaseLabel }}</h3>
    <div class="wiki-resizable-panel measurement-scroll" tabindex="0">
      <table>
        <thead>
          <tr><th>Check</th><th>Scope</th><th>Subject</th><th>Observed</th><th>Budget</th><th>Verdict</th></tr>
        </thead>
        <tbody>
          <tr v-if="!checks.length"><td colspan="6">No measurement has been persisted yet.</td></tr>
          <tr v-for="check in checks" :key="`${check.key}:${check.subject}`">
            <td>{{ check.key }}</td>
            <td>{{ check.scope }}</td>
            <td>{{ check.subject ?? '—' }}</td>
            <td>{{ check.observed ?? '—' }}</td>
            <td>{{ budget(check) }}</td>
            <td :class="`verdict-${check.verdict}`">{{ check.verdict }}{{ check.reason ? `: ${check.reason}` : '' }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
h3 { font-size: 12px; margin-bottom: 8px; }
table { border-collapse: collapse; min-width: 820px; font-size: 11px; }
th, td { border-bottom: 1px solid var(--bg-surface0); padding: 6px 8px; text-align: left; white-space: nowrap; }
th { color: var(--text-sub); }
.verdict-ok { color: var(--green); }
.verdict-breach { color: var(--red); }
.verdict-skipped { color: var(--peach); }
</style>
