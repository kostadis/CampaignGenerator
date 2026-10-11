import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { useConfigStore } from '../../stores/config'
import PathField from './PathField.vue'

vi.mock('../../api/client', () => ({ apiFetch: vi.fn() }))
import { apiFetch } from '../../api/client'
const apiFetchMock = vi.mocked(apiFetch)

function mountField(props: Record<string, unknown>) {
  return mount(PathField, { props: { label: 'Transcript', modelValue: '', ...props } })
}

describe('PathField', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useConfigStore().resolved = {
      campaign_dir: '/campaigns/obelisk',
      runtime: { session_dir: '/campaigns/obelisk/summaries/20261010' },
    }
    vi.useFakeTimers()
    apiFetchMock.mockReset()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('resolves a relative path against session_dir and shows the hint', () => {
    const wrapper = mountField({ modelValue: 'session.vtt' })
    expect(wrapper.find('.resolved-hint').text())
      .toBe('→ /campaigns/obelisk/summaries/20261010/session.vtt')
  })

  it('resolves against campaign_dir when asked', () => {
    const wrapper = mountField({ modelValue: 'docs/party.md', resolveBase: 'campaign' })
    expect(wrapper.find('.resolved-hint').text()).toBe('→ /campaigns/obelisk/docs/party.md')
  })

  it('prefers an explicit baseDir', () => {
    const wrapper = mountField({ modelValue: 'a.md', baseDir: '/tmp/x/' })
    expect(wrapper.find('.resolved-hint').text()).toBe('→ /tmp/x/a.md')
  })

  it('shows no hint for absolute, home-relative, or absolute-mode paths', () => {
    expect(mountField({ modelValue: '/abs/a.md' }).find('.resolved-hint').exists()).toBe(false)
    expect(mountField({ modelValue: '~/a.md' }).find('.resolved-hint').exists()).toBe(false)
    expect(mountField({ modelValue: 'rel', absolute: true }).find('.resolved-hint').exists()).toBe(false)
  })

  it('checks the resolved path after a 300ms debounce and marks it found', async () => {
    apiFetchMock.mockResolvedValue({ exists: true })
    const wrapper = mountField({ modelValue: 'session.vtt' })

    await vi.advanceTimersByTimeAsync(299)
    expect(apiFetchMock).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    await flushPromises()

    expect(apiFetchMock).toHaveBeenCalledWith(
      `/api/config/path-status?path=${encodeURIComponent('/campaigns/obelisk/summaries/20261010/session.vtt')}`,
    )
    expect(wrapper.find('.status.ok').exists()).toBe(true)
  })

  it('marks a missing path as not found', async () => {
    apiFetchMock.mockResolvedValue({ exists: false })
    const wrapper = mountField({ modelValue: '/nope.md' })
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(wrapper.find('.status.missing').text()).toContain('not found')
  })

  it('never checks output paths', async () => {
    const wrapper = mountField({ modelValue: '/out.md', isOutput: true })
    await vi.advanceTimersByTimeAsync(300)
    expect(apiFetchMock).not.toHaveBeenCalled()
    expect(wrapper.find('.status').exists()).toBe(false)
  })

  it('shows no status when the check fails', async () => {
    apiFetchMock.mockRejectedValue(new Error('offline'))
    const wrapper = mountField({ modelValue: '/a.md' })
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()
    expect(wrapper.find('.status').exists()).toBe(false)
  })

  it('emits update:modelValue on input', async () => {
    const wrapper = mountField({ modelValue: '' })
    await wrapper.find('input').setValue('new.md')
    expect(wrapper.emitted('update:modelValue')).toEqual([['new.md']])
  })
})
