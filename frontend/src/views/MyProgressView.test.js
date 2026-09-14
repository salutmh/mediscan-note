/**
 * 진행현황 — 케이스별 학습 이력.
 *
 * 여기서 지키려는 것
 * ----------------
 *  - 여기 숫자는 **내가 표시한 영역과 기준 마스크의 일치도**다.
 *    케이스의 의학적 난이도가 아니라고 화면이 말해야 한다
 *  - `학습완료`는 한 번이라도 일치 판정을 받은 것이고 **취소되지 않는다**.
 *    그 뒤 다시 틀리면 `복습필요`가 함께 붙는다 (배타적이지 않다)
 *  - 값이 없으면 0 으로 채우지 않는다
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const listCases = vi.fn()
const listWrongNotes = vi.fn()
vi.mock('../api/endpoints', () => ({
  listCases: (...a) => listCases(...a),
  listWrongNotes: (...a) => listWrongNotes(...a),
}))

const MyProgressView = (await import('./MyProgressView.vue')).default

const stubs = { RouterLink: { props: ['to'], template: '<a><slot /></a>' } }
const mountView = () => mount(MyProgressView, { global: { stubs } })

const caseOf = (over = {}) => ({
  case_id: 'VS-SEG-202',
  body_part: 'brain_mri',
  disease: 'vestibular_schwannoma',
  has_matched: false,
  needs_review: false,
  progress: null,
  ...over,
})

beforeEach(() => {
  listCases.mockReset()
  listWrongNotes.mockReset()
  listCases.mockResolvedValue({ cases: [caseOf()] })
  listWrongNotes.mockResolvedValue({ items: [] })
})

describe('전체 진행', () => {
  it('학습완료 수와 전체를 함께 보여준다', async () => {
    listCases.mockResolvedValue({
      cases: [
        caseOf({ case_id: 'A', has_matched: true }),
        caseOf({ case_id: 'B' }),
        caseOf({ case_id: 'C' }),
      ],
    })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.hero-count').text()).toContain('1 / 3')
    expect(wrapper.find('.gauge-value').text()).toContain('33')
  })

  it('아무것도 안 풀었으면 0 / N 으로 시작한다', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.hero-count').text()).toContain('0 / 1')
  })
})

describe('케이스별 이력', () => {
  it('시도·첫·최근·최고를 함께 보여준다', async () => {
    listCases.mockResolvedValue({
      cases: [
        caseOf({
          has_matched: true,
          progress: { attempts: 3, first_dice: 0.1, latest_dice: 0.9, best_dice: 0.9 },
        }),
      ],
    })
    const wrapper = mountView()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('VS-SEG-202')
    expect(text).toContain('10%')
    expect(text).toContain('90%')
  })

  it('학습완료와 복습필요는 **동시에** 나올 수 있다', async () => {
    // 맞힌 뒤 다시 틀리면 둘 다 참이다 — 배타적으로 다루면 상태가 사라진다
    listCases.mockResolvedValue({
      cases: [
        caseOf({
          has_matched: true,
          needs_review: true,
          progress: { attempts: 2, first_dice: 0.9, latest_dice: 0.2, best_dice: 0.9 },
        }),
      ],
    })
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('복습필요')
  })
})

describe('오해를 막는 문구', () => {
  it('숫자가 케이스 난이도가 아니라고 못 박는다', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('의학적 난이도를 뜻하지 않습니다')
  })

  it('학습완료가 취소되지 않는다고 설명한다', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('취소되지 않습니다')
  })
})
