import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import RunCommandBar from './RunCommandBar.vue'

describe('RunCommandBar', () => {
  const writeText = vi.fn<(text: string) => Promise<void>>()

  beforeEach(() => {
    vi.useFakeTimers()
    writeText.mockReset().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText } })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows a placeholder and no copy button when there is no command', () => {
    const wrapper = mount(RunCommandBar, { props: { command: '' } })
    expect(wrapper.text()).toContain('Run a stage to see the exact command.')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('copies the command and resets the label after 1.5s', async () => {
    const wrapper = mount(RunCommandBar, { props: { command: 'python prep.py --beat x' } })
    expect(wrapper.find('pre').text()).toBe('python prep.py --beat x')

    await wrapper.find('button').trigger('click')
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith('python prep.py --beat x')
    expect(wrapper.find('button').text()).toBe('Copied!')

    await vi.advanceTimersByTimeAsync(1500)
    expect(wrapper.find('button').text()).toBe('Copy')
  })
})
