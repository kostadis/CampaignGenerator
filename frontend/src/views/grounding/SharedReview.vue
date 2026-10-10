<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import ReviewLauncher from '../../components/ReviewLauncher.vue'

// One page, two queues: /grounding/review and /npcs/review differ only in the
// review kind (route meta) and, for NPCs, the subjects ticked on NPC Dossiers.
const route = useRoute()
const context = computed(() => (route.meta.reviewContext === 'npc' ? 'npc' : 'grounding'))
const selected = computed(() => {
  const q = route.query.subject
  return (Array.isArray(q) ? q : q ? [q] : []).filter((s): s is string => typeof s === 'string' && s !== '')
})
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Shared review</h2>
      <p v-if="context === 'npc'" class="subtitle">
        The review queue for NPC dossiers: decisions, corrections, identity rulings, exact draft sign-offs and
        private reviewer links. Dossiers are linked, drafted and verified on the
        <RouterLink to="/npcs/dossiers">NPC dossiers</RouterLink> page.
      </p>
      <p v-else class="subtitle">
        The review queue for grounding documents: decisions, corrections, identity rulings, exact sign-offs and
        private reviewer links. Drafts are built on the <RouterLink to="/grounding/summary-native">Summary-native</RouterLink>
        page, which also holds claims review and whole-bundle promotion.
      </p>
    </div>
    <ReviewLauncher :key="context" :context="context" :selected="selected" />
  </div>
</template>

<style scoped>
.page { padding: 20px 24px; max-width: 1400px; height: 100%; overflow-y: auto; box-sizing: border-box; }
.page-header { margin-bottom: 20px; }
.page-header h2 { font-size: 16px; font-weight: 700; color: var(--text); margin-bottom: 4px; }
.subtitle { font-size: 12px; color: var(--text-muted); }
</style>
