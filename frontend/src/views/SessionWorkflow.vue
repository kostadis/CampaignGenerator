<script setup lang="ts">
import WizardShell from '../components/wizard/WizardShell.vue'
import type { WizardStep } from '../components/wizard/WizardShell.vue'

const steps: WizardStep[] = [
  { number: 1, label: 'Session Config', path: '/workflow/config' },
  { number: 2, label: 'Editor Config', path: '/workflow/editor', queryStage: 'config' },
  { number: 3, label: 'Enhance Summary', path: '/workflow/editor', queryStage: 'enhance' },
  { number: 4, label: 'Extract Quotes', path: '/workflow/editor', queryStage: 'extract' },
  { number: 5, label: 'Plan & Check', path: '/workflow/editor', queryStage: 'plan' },
  { number: 6, label: 'Editor', path: '/workflow/editor', queryStage: 'edit' },
]
</script>

<template>
  <WizardShell :steps="steps">
    <router-view />
  </WizardShell>
</template>
