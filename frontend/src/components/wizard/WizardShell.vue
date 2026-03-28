<script setup lang="ts">
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'

export interface WizardStep {
  label: string
  path: string
  number: number
}

const props = defineProps<{
  steps: WizardStep[]
}>()

const router = useRouter()
const route = useRoute()

const currentIndex = computed(() =>
  props.steps.findIndex(s => route.path === s.path)
)

const canPrev = computed(() => currentIndex.value > 0)
const canNext = computed(() => currentIndex.value < props.steps.length - 1)

function navigate(path: string) {
  router.push(path)
}

function prev() {
  if (canPrev.value) {
    navigate(props.steps[currentIndex.value - 1].path)
  }
}

function next() {
  if (canNext.value) {
    navigate(props.steps[currentIndex.value + 1].path)
  }
}
</script>

<template>
  <div class="wizard-shell">
    <!-- Step indicators -->
    <div class="wizard-header">
      <div class="steps">
        <template v-for="(step, i) in steps" :key="step.path">
          <div
            class="step"
            :class="{
              active: i === currentIndex,
              completed: i < currentIndex,
              clickable: true,
            }"
            @click="navigate(step.path)"
          >
            <div class="step-number">{{ step.number }}</div>
            <div class="step-label">{{ step.label }}</div>
          </div>
          <div v-if="i < steps.length - 1" class="step-connector" :class="{ filled: i < currentIndex }" />
        </template>
      </div>

      <div class="wizard-nav">
        <button class="btn-neutral btn-sm" :disabled="!canPrev" @click="prev">&larr; Prev</button>
        <button class="btn-neutral btn-sm" :disabled="!canNext" @click="next">Next &rarr;</button>
      </div>
    </div>

    <!-- Content -->
    <div class="wizard-content">
      <slot />
    </div>
  </div>
</template>

<style scoped>
.wizard-shell {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.wizard-header {
  background: var(--bg-mantle);
  border-bottom: 1px solid var(--bg-surface0);
  padding: 10px 20px;
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
}

.steps {
  display: flex;
  align-items: center;
  gap: 0;
  flex: 1;
}

.step {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background .1s;
}
.step:hover { background: #252535; }

.step-number {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  font-weight: 700;
  background: var(--bg-surface0);
  color: var(--text-muted);
  flex-shrink: 0;
}

.step.active .step-number {
  background: var(--mauve);
  color: var(--bg-base);
}
.step.completed .step-number {
  background: var(--green);
  color: var(--bg-base);
}

.step-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  white-space: nowrap;
}
.step.active .step-label { color: var(--text); }
.step.completed .step-label { color: var(--text-sub); }

.step-connector {
  width: 24px;
  height: 2px;
  background: var(--bg-surface0);
  flex-shrink: 0;
}
.step-connector.filled { background: var(--green); }

.wizard-nav {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.wizard-content {
  flex: 1;
  overflow-y: auto;
}
</style>
