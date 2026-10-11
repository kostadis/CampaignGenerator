<script setup lang="ts">
import { ref } from 'vue'
import { useGroundingRun } from '../../composables/useGroundingRun'
import AuthorityLedgerPanel from '../../components/AuthorityLedgerPanel.vue'

// Rulings (spec 035): the reviewed-authority ledger, off the Summary-native build flow. A source-correction
// proposal reads the same summaries directory Summary-native builds from (grounding.yaml summary_native).
const summariesDir = ref('')
useGroundingRun('summary_native', { summaries_dir: summariesDir })
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Rulings</h2>
      <p class="subtitle">
        The reviewed-authority ledger: GM rulings and corrections, staged and applied to the maintained summaries
        so every rebuild keeps them. Rebuild the affected documents on
        <RouterLink to="/grounding/summary-native">Summary-native</RouterLink> afterwards.
      </p>
    </div>
    <AuthorityLedgerPanel :summaries-dir="summariesDir" />
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 1400px; height: 100%; overflow-y: auto; box-sizing: border-box; }
.page-header { margin-bottom: 20px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }
</style>
