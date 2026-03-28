import { defineStore } from 'pinia'
import { reactive } from 'vue'

export interface ProcessState {
  output: string
  status: 'idle' | 'running' | 'done' | 'error'
  returnCode: number | null
}

export const useProcessStore = defineStore('process', () => {
  const processes = reactive<Map<string, ProcessState>>(new Map())

  function get(key: string): ProcessState {
    if (!processes.has(key)) {
      processes.set(key, { output: '', status: 'idle', returnCode: null })
    }
    return processes.get(key)!
  }

  function isRunning(key: string): boolean {
    return processes.get(key)?.status === 'running'
  }

  function hasAnyRunning(): boolean {
    for (const p of processes.values()) {
      if (p.status === 'running') return true
    }
    return false
  }

  return { processes, get, isRunning, hasAnyRunning }
})
