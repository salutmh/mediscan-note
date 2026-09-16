/**
 * 복습노트 목록.
 *
 * 여기서 지키려는 것
 * ----------------
 *  - **먼저 보고 그다음 다시 푼다.** 카드 버튼은 오답 상세로 간다 —
 *    바로 재도전으로 보내면 무엇을 틀렸는지 못 본 채 다시 칠하게 된다
 *  - 재도전 경과(최근·최고)를 보여준다. "틀린 것 목록"이 아니라
 *    "얼마나 가까워지고 있는지"가 이 화면의 요점이다
 *  - 값이 없으면 0 으로 채우지 않는다
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const listWrongNotes = vi.fn()
vi.mock('../api/endpoints', () => ({ listWrongNotes: (...a) => listWrongNotes(...a) }))

const WrongNotesView = (await import('./WrongNotesView.vue')).default

const stubs = { RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } }
const mountView = () => mount(WrongNotesView, { global: { stubs } })

const item = (over = {}) => ({
  case_id: 'VS-SEG-203',
  body_part: 'brain_mri',
  disease: 'vestibular_schwannoma',
  thumbnail_url: 'http://x/t.png',
  grade: 'partial_match',
  attempted_at: new Date().toISOString(),
  latest_dice: 0.39,
  best_dice: 0.52,
  attempts: 2,
  ...over,
})

beforeEach(() => {
  listWrongNotes.mockReset()
  listWrongNotes.mockResolvedValue({ items: [item()] })
})

describe('목록', () => {
  it('카드에 케이스와 판정을 보여준다', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.findAll('.note-card')).toHaveLength(1)
    expect(wrapper.text()).toContain('VS-SEG-203')
    expect(wrapper.text()).toContain('일부 일치')
  })

  it('재도전 경과(최근·최고)를 보여준다', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('39%')
    expect(wrapper.text()).toContain('52%')
  })

  it('점수가 없으면 0% 대신 없다고 쓴다', async () => {
    // **0점과 기록 없음은 다른 상태다**
    listWrongNotes.mockResolvedValue({ items: [item({ latest_dice: null, best_dice: null })] })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('아직 점수 기록이 없습니다')
    expect(wrapper.text()).not.toContain('0%')
  })
})

describe('다음 행동', () => {
  it('바로 재도전이 아니라 **오답 상세**로 보낸다', async () => {
    // 무엇을 틀렸는지 못 본 채 다시 칠하면 같은 실수를 반복한다
    const wrapper = mountView()
    await flushPromises()

    const cta = wrapper.find('.note-card a.btn')
    expect(cta.text()).toContain('무엇을 놓쳤는지 보기')
    expect(cta.attributes('data-to')).toContain('wrong-note-detail')
  })
})

describe('필터', () => {
  it('판정별로 거르고 개수를 함께 보여준다', async () => {
    listWrongNotes.mockResolvedValue({
      items: [item(), item({ case_id: 'VS-SEG-204', grade: 'mismatch' })],
    })
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.findAll('.note-card')).toHaveLength(2)

    const only = wrapper.findAll('.filters button').find((b) => b.text().includes('기준과 다름'))
    await only.trigger('click')

    expect(wrapper.findAll('.note-card')).toHaveLength(1)
    expect(wrapper.text()).toContain('VS-SEG-204')
  })
})

describe('비어 있을 때', () => {
  it('복습할 것이 없으면 케이스 목록으로 안내한다', async () => {
    listWrongNotes.mockResolvedValue({ items: [] })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('아직 복습할 기록이 없습니다')
    expect(wrapper.find('.empty a').text()).toContain('케이스 목록')
  })
})


/**
 * `grade: "match"` 인 항목이 이 목록에 들어올 수 있다 (과대 표시, 계약 v0.6).
 * 등급 뱃지만 두면 **"일치인데 왜 여기 있지?"** 가 되므로 이유가 화면에 있어야 한다.
 */
describe('일치했지만 넓게 칠한 케이스', () => {
  const overMarked = () =>
    item({ grade: 'match', latest_dice: 0.62, best_dice: 0.62, review_reason: 'over_marked', area_ratio: 2.21 })

  it('등급 대신 **왜 담겼는지**를 뱃지로 보여준다', async () => {
    listWrongNotes.mockResolvedValue({ items: [overMarked()] })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.badge.float').text()).toBe('넓게 표시')
    // "기준과 일치" 뱃지를 그대로 달면 목록에 있는 이유가 설명되지 않는다
    expect(wrapper.find('.badge.float').text()).not.toContain('일치')
  })

  it('몇 배 칠했는지 숫자로 적는다', async () => {
    listWrongNotes.mockResolvedValue({ items: [overMarked()] })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.why').text()).toContain('2.2배')
  })

  it('기준과 달랐던 케이스는 원래대로 등급 뱃지를 단다', async () => {
    listWrongNotes.mockResolvedValue({ items: [item({ review_reason: 'not_matched' })] })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.why').exists()).toBe(false)
    expect(wrapper.find('.badge.float').text()).not.toBe('넓게 표시')
  })
})
