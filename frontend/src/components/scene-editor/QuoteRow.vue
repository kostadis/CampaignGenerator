<script setup lang="ts">
export interface Quote {
  id: number
  source_file?: string
  block_index?: number
  speaker: string
  character: string
  context: string
  quote_text: string
  scene_index: number | null
  pinned: number
}

const props = defineProps<{
  quote: Quote
  selected: boolean
  expanded: boolean
  /** Show a muted scene label instead of checkbox (used in picker for other-scene quotes). */
  sceneLabel?: string
  /** Disable checkbox (used in picker for already-assigned quotes). */
  disabled?: boolean
}>()

const emit = defineEmits<{
  'toggle-select': [id: number, event: MouseEvent]
  'toggle-expand': [id: number]
  'quick-delete': [id: number]
}>()

function onCheckbox(e: MouseEvent) {
  e.stopPropagation()
  emit('toggle-select', props.quote.id, e)
}

function truncate(text: string, len: number = 120): string {
  return text.length > len ? text.substring(0, len) + '\u2026' : text
}
</script>

<template>
  <div
    class="quote-row"
    :class="{ selected, expanded, disabled }"
    @click="emit('toggle-expand', quote.id)"
  >
    <div class="row-left">
      <input
        v-if="!sceneLabel"
        type="checkbox"
        :checked="selected"
        :disabled="disabled"
        @click="onCheckbox"
        class="row-cb"
      />
      <span v-else class="scene-tag">{{ sceneLabel }}</span>
    </div>
    <div class="row-body">
      <div class="row-header">
        <span class="character">{{ quote.character }}</span>
        <span v-if="quote.context" class="context">{{ quote.context }}</span>
        <button
          v-if="!disabled && !sceneLabel"
          class="quick-del"
          title="Remove from scene"
          @click.stop="emit('quick-delete', quote.id)"
        >&times;</button>
      </div>
      <div class="row-text">
        {{ expanded ? quote.quote_text : truncate(quote.quote_text) }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.quote-row {
  display: flex;
  gap: 8px;
  padding: 6px 10px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: background .1s;
  align-items: flex-start;
}
.quote-row:hover { background: #252535; }
.quote-row.selected { background: #252535; }
.quote-row.expanded { border-left-color: var(--mauve); background: #252535; }
.quote-row.disabled { opacity: 0.5; cursor: default; }

.row-left {
  flex-shrink: 0;
  padding-top: 2px;
}
.row-cb {
  accent-color: var(--mauve);
  cursor: pointer;
}

.scene-tag {
  font-size: 8px;
  font-weight: 700;
  color: var(--text-muted);
  background: var(--bg-surface0);
  padding: 1px 4px;
  border-radius: 2px;
  white-space: nowrap;
}

.row-body { flex: 1; min-width: 0; }

.row-header {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.character {
  font-size: 11px;
  font-weight: 700;
  color: var(--mauve);
}
.context {
  font-size: 10px;
  color: var(--text-muted);
  font-style: italic;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
}
.quick-del {
  font-size: 14px;
  color: var(--text-muted);
  background: none;
  border: none;
  cursor: pointer;
  padding: 0 2px;
  line-height: 1;
  opacity: 0;
  transition: opacity .1s;
}
.quote-row:hover .quick-del { opacity: 0.6; }
.quick-del:hover { opacity: 1 !important; color: var(--red); }

.row-text {
  font-size: 11px;
  color: var(--text-sub);
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.quote-row.expanded .row-text {
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
