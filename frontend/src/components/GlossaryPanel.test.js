/**
 * 의학용어 사전 패널 (화면 2 우측).
 *
 * 지키려는 것
 * ----------
 *  - **용어를 화면에서 만들지 않는다.** 서버가 준 것만 그대로 보여준다
 *  - 콘텐츠가 없으면 비워 두고 그렇게 말한다 (지어내지 않는다)
 *  - 사전이 실패해도 **판독은 계속할 수 있어야 한다** — 실패 문구가 그렇게 말해야 한다
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const getGlossary = vi.fn()
vi.mock('../api/endpoints', () => ({ getGlossary: (...a) => getGlossary(...a) }))

const GlossaryPanel = (await import('./GlossaryPanel.vue')).default

const TERMS = [
  { term: '소뇌교각 (cerebellopontine angle, CPA)', description: '발생 부위. (Applied Radiology 2019)' },
  { term: 'porus acusticus', description: '내이도를 벗어나는 지점.' },
]

beforeEach(() => {
  getGlossary.mockReset()
  getGlossary.mockResolvedValue({ terms: TERMS, source: 'literature_based' })
})

function mountPanel(props = {}) {
  return mount(GlossaryPanel, {
    props: { disease: 'vestibular_schwannoma', diseaseLabel: '전정신경초종', ...props },
  })
}

describe('용어 표시', () => {
  it('서버가 준 용어를 그대로 보여준다', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    expect(getGlossary).toHaveBeenCalledWith('vestibular_schwannoma')
    expect(wrapper.text()).toContain('cerebellopontine angle, CPA')
    expect(wrapper.text()).toContain('porus acusticus')
  })

  it('설명은 눌렀을 때 펼쳐지고 출처 표기까지 그대로 나온다', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).not.toContain('Applied Radiology 2019')
    await wrapper.findAll('.g-item')[0].trigger('click')
    expect(wrapper.text()).toContain('발생 부위. (Applied Radiology 2019)')
  })

  it('검색어로 걸러낸다', async () => {
    const wrapper = mountPanel()
    await flushPromises()

    await wrapper.find('.g-search input').setValue('porus')
    expect(wrapper.findAll('.g-item')).toHaveLength(1)
    expect(wrapper.text()).toContain('porus acusticus')
  })

  it('이 케이스의 소견이 아니라는 것을 밝힌다', async () => {
    // 문헌 일반론을 케이스 소견처럼 읽으면 안 된다 (해설 3층 분리와 같은 규칙)
    const wrapper = mountPanel()
    await flushPromises()
    expect(wrapper.text()).toContain('이 케이스의 소견이 아닙니다')
  })
})

describe('비어 있거나 실패했을 때', () => {
  it('용어가 없으면 지어내지 않고 없다고 쓴다', async () => {
    getGlossary.mockResolvedValue({ terms: [] })
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('준비된 용어가 없습니다')
    expect(wrapper.findAll('.g-item')).toHaveLength(0)
  })

  it('불러오지 못해도 판독은 계속할 수 있다고 말한다', async () => {
    getGlossary.mockRejectedValue(new Error('boom'))
    const wrapper = mountPanel()
    await flushPromises()

    expect(wrapper.text()).toContain('판독과 제출은 그대로 진행할 수 있습니다')
  })

  it('질환 코드가 없으면 요청조차 하지 않는다', async () => {
    const wrapper = mountPanel({ disease: null })
    await flushPromises()

    expect(getGlossary).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('준비된 용어가 없습니다')
  })
})
