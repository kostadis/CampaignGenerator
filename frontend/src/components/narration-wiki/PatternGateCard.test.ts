import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import PatternGateCard from './PatternGateCard.vue'

function buttons(wrapper: ReturnType<typeof mount>) {
  const [accept, reject] = wrapper.findAll('button')
  return { accept: accept!, reject: reject! }
}

describe('PatternGateCard', () => {
  it('disables both rulings until a pattern slug is entered', async () => {
    const wrapper = mount(PatternGateCard)
    const { accept, reject } = buttons(wrapper)
    expect(accept.attributes('disabled')).toBeDefined()
    expect(reject.attributes('disabled')).toBeDefined()

    await wrapper.find('input[type="text"]').setValue('   ')
    expect(accept.attributes('disabled')).toBeDefined()

    await wrapper.find('input[type="text"]').setValue('em-dash-overuse')
    expect(accept.attributes('disabled')).toBeUndefined()
    expect(reject.attributes('disabled')).toBeUndefined()
  })

  it('stays disabled when the host disables it, even with a slug', async () => {
    const wrapper = mount(PatternGateCard, { props: { disabled: true } })
    await wrapper.find('input[type="text"]').setValue('em-dash-overuse')
    expect(buttons(wrapper).accept.attributes('disabled')).toBeDefined()
  })

  it('accepts at campaign tier by default with no override', async () => {
    const wrapper = mount(PatternGateCard)
    await wrapper.find('input[type="text"]').setValue('em-dash-overuse')
    await buttons(wrapper).accept.trigger('click')

    expect(wrapper.emitted('rule')).toEqual([[{
      pattern_slug: 'em-dash-overuse',
      decision: 'accept',
      tier: 'campaign',
      named_portable_override: false,
      rationale: null,
    }]])
  })

  it('shows the override controls only for the portable tier', async () => {
    const wrapper = mount(PatternGateCard)
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
    await wrapper.find('select').setValue('portable')
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(true)
    expect(wrapper.find('textarea').exists()).toBe(true)
  })

  it('carries the named-content override and rationale on a portable accept', async () => {
    const wrapper = mount(PatternGateCard)
    await wrapper.find('input[type="text"]').setValue('em-dash-overuse')
    await wrapper.find('select').setValue('portable')
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await wrapper.find('textarea').setValue('  generic enough  ')
    await buttons(wrapper).accept.trigger('click')

    expect(wrapper.emitted('rule')![0]![0]).toMatchObject({
      tier: 'portable',
      named_portable_override: true,
      rationale: 'generic enough',
    })
  })

  it('drops tier and override on a reject', async () => {
    const wrapper = mount(PatternGateCard)
    await wrapper.find('input[type="text"]').setValue('em-dash-overuse')
    await wrapper.find('select').setValue('portable')
    await wrapper.find('input[type="checkbox"]').setValue(true)
    await buttons(wrapper).reject.trigger('click')

    expect(wrapper.emitted('rule')![0]![0]).toMatchObject({
      decision: 'reject',
      tier: null,
      named_portable_override: false,
    })
  })
})
