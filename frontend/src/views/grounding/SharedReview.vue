<script setup lang="ts">
import ReviewLauncher from '../../components/ReviewLauncher.vue'
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Shared review</h2>
      <p class="subtitle">
        The review queue for grounding documents: decisions, corrections, identity rulings, exact sign-offs and
        private reviewer links. Drafts are built on the <RouterLink to="/grounding/summary-native">Summary-native</RouterLink>
        page, which also holds claims review and whole-bundle promotion.
      </p>
    </div>
    <ReviewLauncher context="grounding" />
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 1400px; height: 100%; overflow-y: auto; box-sizing: border-box; }
.page-header { margin-bottom: 20px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }
</style>
