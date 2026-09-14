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
