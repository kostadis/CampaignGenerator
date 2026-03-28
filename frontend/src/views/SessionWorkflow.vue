<script setup lang="ts">
import WizardShell from '../components/wizard/WizardShell.vue'
import type { WizardStep } from '../components/wizard/WizardShell.vue'

const steps: WizardStep[] = [
  { number: 1, label: 'Session Config', path: '/workflow/config' },
  { number: 2, label: 'VTT Summary', path: '/workflow/vtt' },
  { number: 3, label: 'Scene Extraction', path: '/workflow/extract' },
  { number: 4, label: 'Session Doc Editor', path: '/workflow/editor' },
]
</script>

<template>
  <WizardShell :steps="steps">
    <router-view />
  </WizardShell>
</template>
