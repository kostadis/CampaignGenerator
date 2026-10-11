import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import BackendModelPicker from './BackendModelPicker.vue'

describe('BackendModelPicker', () => {
  it('labels the blank option with the stored backend', () => {
    const wrapper = mount(BackendModelPicker, {
      props: { configKey: 'summary_native.extract', storedBackend: 'dgx' },
    })
    expect(wrapper.find('option').text()).toBe('stored (dgx)')
    expect(wrapper.text()).toContain('summary_native.extract.backend')
  })

  it('placeholders the stored model while the backend is unchanged', async () => {
    const wrapper = mount(BackendModelPicker, {
      props: { configKey: 'k', storedBackend: 'dgx', storedModel: 'qwen3' },
    })
    const input = wrapper.find('input')
    expect(input.attributes('placeholder')).toBe('qwen3')

    await wrapper.setProps({ backend: 'dgx' })
    expect(input.attributes('placeholder')).toBe('qwen3')
  })

  it("placeholders the chosen backend's default when it differs from the stored one", async () => {
    const wrapper = mount(BackendModelPicker, {
      props: { configKey: 'k', storedBackend: 'dgx', storedModel: 'qwen3', backend: 'anthropic' },
    })
    expect(wrapper.find('input').attributes('placeholder')).toBe('anthropic default')
  })

  it('emits v-model updates for backend and model', async () => {
    const wrapper = mount(BackendModelPicker, { props: { configKey: 'k' } })
    await wrapper.find('select').setValue('openrouter')
    await wrapper.find('input').setValue('some/model')
    expect(wrapper.emitted('update:backend')).toEqual([['openrouter']])
    expect(wrapper.emitted('update:model')).toEqual([['some/model']])
  })

  it('hides the help lines when showHelp is false', () => {
    const wrapper = mount(BackendModelPicker, { props: { configKey: 'k', showHelp: false } })
    expect(wrapper.find('.field-help').exists()).toBe(false)
  })
})
