<script setup lang="ts">
export interface Scene {
  index: number
  narrator: string
  scene: string
  focus: string
  has_extraction: boolean
  has_output: boolean
  filename: string
}

defineProps<{
  scenes: Scene[]
  currentScene: number | null
}>()

const emit = defineEmits<{
  select: [index: number]
}>()
</script>

<template>
  <div class="scenes">
    <h2>Scenes</h2>
    <div class="scene-list">
      <div v-if="scenes.length === 0" class="empty-msg">
        No plan yet.<br>
        Click <b>Extract</b> in the header<br>
        to run passes 1-4.
      </div>
      <div
        v-for="s in scenes"
        :key="s.index"
        class="scene-item"
        :class="{ active: currentScene === s.index }"
        @click="emit('select', s.index)"
      >
        <div class="num">Scene {{ s.index }}</div>
        <div class="narrator">{{ s.narrator }}</div>
        <div class="sname">{{ s.scene || '\u2014' }}</div>
        <div class="badges">
          <span v-if="s.has_extraction" class="badge b-ext">Extracted</span>
          <span v-if="s.has_output" class="badge b-nar">Narrated</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.scenes {
  background: var(--bg-mantle);
  border-right: 1px solid var(--bg-surface0);
  overflow-y: auto;
}
.scenes h2 {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: .08em;
  color: var(--text-muted);
  padding: 10px 12px 4px;
}
.empty-msg {
  padding: 12px;
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.6;
}
.empty-msg b { color: var(--mauve); }

.scene-item {
  padding: 7px 12px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: background .1s;
}
.scene-item:hover { background: #252535; }
.scene-item.active { background: #252535; border-left-color: var(--mauve); }

.num { font-size: 10px; color: var(--text-muted); font-weight: 600; }
.narrator { font-size: 12px; font-weight: 600; }
.sname {
  font-size: 11px;
  color: var(--text-sub);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.badges { display: flex; gap: 3px; margin-top: 3px; }
.badge {
  font-size: 9px;
  font-weight: 700;
  padding: 1px 5px;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: .05em;
}
.b-ext { background: #1e3a5f; color: var(--blue); }
.b-nar { background: #1e3a2a; color: var(--green); }
</style>
