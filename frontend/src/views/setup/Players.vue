<script setup lang="ts">
import PlayersEditor from '../../components/shared/PlayersEditor.vue'
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2>Players</h2>
      <p class="subtitle">
        Who is at the table. One row per human — their name, every label a recording has
        used for them, and the characters they play.
      </p>
    </div>

    <div class="explainer">
      <p>
        This is the <strong>one place</strong> a player's identity is authored. The roster
        block in a narration prompt, the speaker labels in a transcript, and the
        <code>Player:</code> line stamped into a converted character sheet are all
        rendered from here. Editing any of those elsewhere is drift, and
        <code>players check</code> will report it.
      </p>
      <p>
        Characters, sheets, backstories and their voice and example files live on the
        <router-link to="/grounding/party">Party Document</router-link> page. This page
        owns the people; that one owns the characters.
      </p>
    </div>

    <PlayersEditor />
  </div>
</template>

<style scoped>
.explainer {
  margin-bottom: 12px; padding: 10px 12px;
  background: var(--bg-mantle); border-radius: 4px;
  border: 1px solid var(--bg-surface0);
  font-size: 11px; color: var(--text-sub); line-height: 1.6;
}
.explainer p { margin: 0 0 6px; }
.explainer p:last-child { margin-bottom: 0; }
.explainer code {
  font-family: var(--font-mono, monospace);
  background: var(--bg-surface0); padding: 1px 4px; border-radius: 3px;
}
</style>
