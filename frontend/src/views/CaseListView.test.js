/**
 * 화면 1 — 부위 필터 탭.
 *
 * 여기서 지키려는 것: **없는 콘텐츠를 있는 것처럼 보여주지 않는다.**
 * 예전에는 계약에 정의된 5개 부위를 모두 탭으로 깔아뒀는데 실제 케이스는 뇌 MRI 뿐이라,
 * 나머지 4개는 눌러도 빈 목록이었다. 첫 사용자가 빈 화면을 네 번 만나게 된다.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const listCases = vi.fn()
vi.mock('../api/endpoints', () => ({ listCases: (...args) => listCases(...args) }))

const CaseListView = (await import('./CaseListView.vue')).default

const RouterLinkStub = { props: ['to'], template: '<a><slot /></a>' }
const mountView = () =>
  mount(CaseListView, { global: { stubs: { RouterLink: RouterLinkStub } } })

const brainCase = (id) => ({
  case_id: id,
  body_part: 'brain_mri',
  disease: 'vestibular_schwannoma',
  thumbnail_url: `http://x/${id}.png`,
  has_matched: false,
  needs_review: false,
  gradable: true,
})

beforeEach(() => {
  listCases.mockReset()
})

describe('부위 필터 탭', () => {
  it('부위가 하나뿐이면 탭을 아예 보여주지 않는다', async () => {
    listCases.mockResolvedValue({ cases: [brainCase('VS-SEG-202'), brainCase('VS-SEG-203')] })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.filters').exists()).toBe(false)
    // 탭이 없어도 케이스는 보여야 한다
    expect(wrapper.text()).toContain('VS-SEG-202')
  })

  it('여러 부위가 있으면 "전체" + 실제 부위만 탭으로 만든다', async () => {
    listCases.mockResolvedValue({
      cases: [brainCase('VS-SEG-202'), { ...brainCase('CXR-0001'), body_part: 'chest_xray' }],
    })

    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('.filters button').map((b) => b.text())
    expect(labels).toEqual(['전체', '뇌 MRI', '흉부 X-ray'])
    // 케이스가 없는 부위(뇌 CT, 복부 CT, 무릎)는 탭에 없어야 한다
    expect(labels).not.toContain('뇌 CT')
    expect(labels).not.toContain('복부 CT')
  })

  it('부위 탭을 누르면 그 부위로 다시 조회한다', async () => {
    listCases.mockResolvedValue({
      cases: [brainCase('VS-SEG-202'), { ...brainCase('CXR-0001'), body_part: 'chest_xray' }],
    })

    const wrapper = mountView()
    await flushPromises()

    const chestTab = wrapper.findAll('.filters button').find((b) => b.text() === '흉부 X-ray')
    await chestTab.trigger('click')
    await flushPromises()

    expect(listCases).toHaveBeenLastCalledWith('chest_xray')
  })

  it('부위를 필터한 뒤에도 탭 목록이 사라지지 않는다', async () => {
    // 필터된 응답으로 탭을 다시 만들면 탭이 하나만 남아 다른 부위로 못 돌아간다
    listCases.mockResolvedValueOnce({
      cases: [brainCase('VS-SEG-202'), { ...brainCase('CXR-0001'), body_part: 'chest_xray' }],
    })
    const wrapper = mountView()
    await flushPromises()

    listCases.mockResolvedValueOnce({ cases: [{ ...brainCase('CXR-0001'), body_part: 'chest_xray' }] })
    await wrapper.findAll('.filters button').find((b) => b.text() === '흉부 X-ray').trigger('click')
    await flushPromises()

    expect(wrapper.findAll('.filters button').map((b) => b.text())).toEqual([
      '전체',
      '뇌 MRI',
      '흉부 X-ray',
    ])
  })
})

describe('상태 표시', () => {
  it('학습완료와 복습필요는 동시에 표시될 수 있다', async () => {
    // 배타적이지 않다 — 맞힌 뒤 다시 틀리면 둘 다 true 다
    listCases.mockResolvedValue({
      cases: [{ ...brainCase('VS-SEG-202'), has_matched: true, needs_review: true }],
    })

    const wrapper = mountView()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('학습완료')
    expect(text).toContain('복습필요')
    expect(text).not.toContain('미시도')
  })

  it('아무 상태도 아니면 미시도로 보여준다', async () => {
    listCases.mockResolvedValue({ cases: [brainCase('VS-SEG-202')] })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('미시도')
  })
})

describe('난이도', () => {
  it('전문가가 지정한 난이도만 표시한다', async () => {
    listCases.mockResolvedValue({
      cases: [
        { ...brainCase('VS-SEG-202'), difficulty: 'hard' },
        { ...brainCase('VS-SEG-203'), difficulty: null },
      ],
    })

    const wrapper = mountView()
    await flushPromises()

    const badges = wrapper.findAll('.badge.difficulty').map((b) => b.text())
    // 지정된 것만 뱃지가 붙는다. 미지정은 아무것도 표시하지 않는다
    // ("표시가 없다 = 아직 판정되지 않았다"가 정확한 의미여야 한다)
    expect(badges).toEqual(['어려움'])
  })

  it('난이도가 하나뿐이거나 없으면 필터를 만들지 않는다', async () => {
    listCases.mockResolvedValue({
      cases: [
        { ...brainCase('VS-SEG-202'), difficulty: 'hard' },
        { ...brainCase('VS-SEG-203'), difficulty: null },
      ],
    })

    const wrapper = mountView()
    await flushPromises()

    // 죽은 컨트롤을 만들지 않는다 — 눌러도 결과가 같은 필터는 없느니만 못하다
    expect(wrapper.findAll('.filters').length).toBe(0)
  })

  it('난이도가 여럿이면 필터로 걸러진다', async () => {
    listCases.mockResolvedValue({
      cases: [
        { ...brainCase('VS-SEG-202'), difficulty: 'hard' },
        { ...brainCase('VS-SEG-203'), difficulty: 'easy' },
      ],
    })

    const wrapper = mountView()
    await flushPromises()

    const easyTab = wrapper.findAll('.filters button').find((b) => b.text() === '쉬움')
    await easyTab.trigger('click')

    expect(wrapper.text()).toContain('VS-SEG-203')
    expect(wrapper.text()).not.toContain('VS-SEG-202')
  })
})

describe('실패·빈 상태', () => {
  it('조회가 실패해도 화면이 깨지지 않고 이유를 보여준다', async () => {
    listCases.mockRejectedValue(Object.assign(new Error('백엔드에 연결할 수 없습니다.')))

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('백엔드에 연결할 수 없습니다.')
  })

  it('케이스가 하나도 없으면 빈 화면 대신 이유를 안내한다', async () => {
    listCases.mockResolvedValue({ cases: [] })

    const wrapper = mountView()
    await flushPromises()

    // 케이스 카드는 없고
    expect(wrapper.findAll('.case-card').length).toBe(0)
    // 대신 빈 상태 안내가 나온다 (아무것도 없는 화면을 보여주지 않는다)
    expect(wrapper.find('.empty').exists()).toBe(true)
    expect(wrapper.text()).toContain('케이스가 없습니다')
  })
})
