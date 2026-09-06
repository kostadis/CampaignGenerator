<script setup lang="ts">
import { computed } from 'vue'
import type { Scene } from './SceneList.vue'

const props = defineProps<{
  open: boolean
  scenes: Scene[]
  batchTokens: number
  busy: boolean
}>()

const emit = defineEmits<{
  cancel: []
  run: []
}>()

const orderedScenes = computed(() =>
  [...props.scenes].sort((left, right) => left.index - right.index),
)
const replacementCount = computed(() =>
  orderedScenes.value.filter(scene => scene.has_output).length,
)

function onBackdrop(event: MouseEvent) {
  if (event.target === event.currentTarget && !props.busy) emit('cancel')
}
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="bundle-backdrop"
      data-testid="narration-bundle-dialog"
      @click="onBackdrop"
    >
      <section
        class="bundle-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="narration-bundle-title"
      >
        <header class="bundle-header">
          <div>
            <h2 id="narration-bundle-title">Narrate all in one call</h2>
            <p>
              {{ orderedScenes.length }} scene{{ orderedScenes.length === 1 ? '' : 's' }}
              in plan order · {{ batchTokens.toLocaleString() }} token total ceiling
            </p>
          </div>
          <button
            class="icon-button"
            type="button"
            aria-label="Cancel bundled narration"
            :disabled="busy"
            @click="emit('cancel')"
          >×</button>
        </header>

        <div class="bundle-notice">
          This sends the displayed scenes in one narration exchange. Files marked
          <strong>will replace</strong> already exist and will be overwritten.
          Every result remains a separate draft for review before assembly.
        </div>

        <ol class="bundle-scenes" aria-label="Bundled narration scene scope">
          <li v-for="scene in orderedScenes" :key="scene.index">
            <span class="scene-index">{{ String(scene.index).padStart(2, '0') }}</span>
            <span class="scene-identity">
              <strong>{{ scene.scene || `Scene ${scene.index}` }}</strong>
              <span>{{ scene.narrator || 'Narrator not assigned' }}</span>
            </span>
            <span class="output-state" :class="{ replace: scene.has_output }">
              {{ scene.has_output ? 'will replace' : 'new' }}
            </span>
          </li>
        </ol>

        <p v-if="replacementCount" class="replacement-summary">
          {{ replacementCount }} existing narration
          {{ replacementCount === 1 ? 'file' : 'files' }} will be replaced.
        </p>
        <p v-if="orderedScenes.length === 0" class="empty-scope" role="alert">
          No plan scenes are available. Create and review the plan before narrating.
        </p>

        <footer class="bundle-actions">
          <button class="btn-neutral" type="button" :disabled="busy" @click="emit('cancel')">
            Cancel
          </button>
          <button
            class="btn-success"
            type="button"
            :disabled="busy || orderedScenes.length === 0"
            @click="emit('run')"
          >{{ busy ? 'Narrating…' : `Narrate ${orderedScenes.length} in one call` }}</button>
        </footer>
      </section>
    </div>
  </Teleport>
</template>

<style scoped>
.bundle-backdrop {
  position: fixed;
  inset: 0;
  z-index: 1000;
  display: grid;
  place-items: center;
  padding: 24px;
  background: rgb(10 10 18 / 78%);
}

.bundle-dialog {
  width: min(660px, 100%);
  max-height: min(720px, calc(100vh - 48px));
  display: flex;
  flex-direction: column;
  background: var(--bg-mantle);
  color: var(--text);
  border: 1px solid var(--bg-surface1);
  border-radius: 8px;
  box-shadow: 0 18px 60px rgb(0 0 0 / 55%);
}

.bundle-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--bg-surface0);
}
.bundle-header h2 { margin: 0; font-size: 17px; color: var(--mauve); }
.bundle-header p { margin: 5px 0 0; font-size: 12px; color: var(--text-muted); }
.icon-button {
  border: 0;
  background: transparent;
  color: var(--text-muted);
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
}
.icon-button:disabled { cursor: default; opacity: .5; }

.bundle-notice {
  margin: 14px 20px 8px;
  padding: 10px 12px;
  border-left: 3px solid var(--blue);
  background: var(--bg-base);
  color: var(--text-sub);
  font-size: 12px;
  line-height: 1.5;
}
.bundle-notice strong { color: var(--peach); }

.bundle-scenes {
  min-height: 0;
  overflow-y: auto;
  list-style: none;
  margin: 6px 20px;
  padding: 0;
  border: 1px solid var(--bg-surface0);
  border-radius: 5px;
}
.bundle-scenes li {
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  padding: 9px 11px;
  border-bottom: 1px solid var(--bg-surface0);
}
.bundle-scenes li:last-child { border-bottom: 0; }
.scene-index { font: 700 11px var(--mono); color: var(--mauve); }
.scene-identity { min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.scene-identity strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.scene-identity span { font-size: 11px; color: var(--text-muted); }
.output-state {
  padding: 2px 7px;
  border-radius: 999px;
  color: var(--green);
  background: rgb(166 209 137 / 12%);
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .04em;
}
.output-state.replace { color: var(--peach); background: rgb(239 159 118 / 12%); }
.replacement-summary,
.empty-scope { margin: 3px 20px 8px; color: var(--text-muted); font-size: 11px; }
.empty-scope { color: var(--red); }
.bundle-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 14px 20px 18px;
  border-top: 1px solid var(--bg-surface0);
}
</style>
