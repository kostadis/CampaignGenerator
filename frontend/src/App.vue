<script setup lang="ts">
import { onMounted } from 'vue'
import { useConfigStore } from './stores/config'
import AppSidebar from './components/layout/AppSidebar.vue'

const config = useConfigStore()

onMounted(async () => {
  try {
    await config.load()
  } catch (e) {
    console.error('Failed to load config:', e)
  }
})
</script>

<template>
  <div class="app-layout">
    <AppSidebar />
    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.app-main {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
</style>
