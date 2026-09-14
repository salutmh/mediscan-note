/**
 * 학습 대시보드.
 *
 * 여기서 지키려는 것
 * ----------------
 *  - **없는 값을 0 으로 채우지 않는다.** 한 번도 안 푼 사람의 비율은 0% 가 아니라
 *    "아직 기록 없음"이다 (0점과 미시도는 다른 상태다)
 *  - "기준과 일치한 비율"의 분모는 **시도한 케이스**다. 전체를 분모로 쓰면
 *    아직 풀지 않은 것을 틀린 것으로 세게 된다
 *  - 숫자는 **내 기록**이지 케이스 난이도가 아니다
 *  - 기간 필터는 최근 활동에만 걸린다
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const getDashboard = vi.fn()
vi.mock('../api/endpoints', () => ({ getDashboard: (...a) => getDashboard(...a) }))
vi.mock('vue-router', () => ({
  RouterLink: { props: ['to'], template: '<a><slot /></a>' },
}))

const DashboardView = (await import('./DashboardView.vue')).default

const stubs = { RouterLink: { props: ['to'], template: '<a><slot /></a>' } }
const mountView = () => mount(DashboardView, { global: { stubs } })

const daysAgo = (n) => new Date(Date.now() - n * 86400000).toISOString()

const EMPTY = {
  totals: { total_cases: 6, matched: 0, needs_review: 0, attempted: 0, total_attempts: 0 },
  recent_activity: [],
  best_dice: null,
}

const ACTIVE = {
  totals: { total_cases: 6, matched: 1, needs_review: 2, attempted: 3, total_attempts: 8 },
  recent_activity: [
    { case_id: 'VS-SEG-202', grade: 'match', dice: 1.0, submitted_at: daysAgo(0), thumbnail_url: 'http://x/a.png' },
    { case_id: 'VS-SEG-204', grade: 'mismatch', dice: 0.04, submitted_at: daysAgo(20), thumbnail_url: null },
  ],
  best_dice: 1.0,
}

beforeEach(() => {
  getDashboard.mockReset()
})

describe('처음 온 사용자', () => {
  it('비율을 0% 로 적지 않고 "아직 기록 없음"이라고 쓴다', async () => {
    // **0% 라고 쓰면 "0점을 받았다"로 읽힌다.** 미시도와 0점은 다른 상태다.
    getDashboard.mockResolvedValue(EMPTY)
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('아직 기록 없음')
    expect(wrapper.text()).toContain('아직 제출한 판독이 없습니다')
  })
})

describe('학습 중인 사용자', () => {
  beforeEach(() => getDashboard.mockResolvedValue(ACTIVE))

  it('진도는 전체 케이스 대비로 센다', async () => {
    const wrapper = mountView()
    await flushPromises()
    // 1 / 6 = 17%
    expect(wrapper.text()).toContain('17')
    expect(wrapper.text()).toContain('총 1 / 6 케이스 학습완료')
  })

  it('기준과 일치한 비율의 분모는 **시도한 케이스**다', async () => {
    // 전체(6)를 분모로 쓰면 17% 지만, 시도한 3개 기준이면 33% 다.
    // 아직 풀지 않은 것을 틀린 것으로 세면 안 된다.
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('33')
    expect(wrapper.text()).toContain('시도한 3개 중 1개가 기준과 일치')
  })

  it('최고 일치도를 보여준다', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('100')
  })

  it('최근 학습 활동을 표로 보여준다', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.findAll('.activity-table tbody tr')).toHaveLength(2)
    expect(wrapper.text()).toContain('VS-SEG-202')
    expect(wrapper.text()).toContain('일치')
  })

  it('기간 필터는 최근 활동에만 걸린다', async () => {
    const wrapper = mountView()
    await flushPromises()

    const week = wrapper.findAll('.range button').find((b) => b.text() === '최근 7일')
    await week.trigger('click')

    // 20일 전 기록은 빠지고, 지표(진도 17%)는 그대로다
    expect(wrapper.findAll('.activity-table tbody tr')).toHaveLength(1)
    expect(wrapper.text()).toContain('17')
    expect(wrapper.text()).not.toContain('VS-SEG-204')
  })

  it('숫자가 케이스 난이도가 아니라고 못 박는다', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('의학적 난이도를 뜻하지 않습니다')
  })
})

describe('실패와 로딩', () => {
  it('불러오는 동안 안내를 보여준다', () => {
    getDashboard.mockReturnValue(new Promise(() => {}))
    expect(mountView().text()).toContain('불러오는 중')
  })

  it('실패하면 사람이 읽을 문장을 보여준다', async () => {
    getDashboard.mockRejectedValue(new Error('서버에 연결하지 못했습니다.'))
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('서버에 연결하지 못했습니다')
  })
})
