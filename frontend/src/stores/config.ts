import { defineStore } from 'pinia'
import { ref } from 'vue'
import { apiFetch, apiPut } from '../api/client'

export const useConfigStore = defineStore('config', () => {
  const values = ref<Record<string, any>>({})
  const models = ref<string[]>([])
  const defaultModel = ref('claude-sonnet-4-6')
  const model = ref('claude-sonnet-4-6')
  const apiKeyPresent = ref(false)
  const cwd = ref('')

  async function load() {
    const [cfg, modelsData, status] = await Promise.all([
      apiFetch('/api/config/'),
      apiFetch('/api/config/models'),
      apiFetch('/api/config/status'),
    ])
    values.value = cfg
    models.value = modelsData.models
    defaultModel.value = modelsData.default
    model.value = cfg.global_model || modelsData.default
    apiKeyPresent.value = status.api_key_present
    cwd.value = status.cwd
  }

  async function save() {
    await apiPut('/api/config/', { values: { ...values.value, global_model: model.value } })
  }

  return { values, models, defaultModel, model, apiKeyPresent, cwd, load, save }
})
