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
const listCases = vi.fn()
vi.mock('../api/endpoints', () => ({
  getDashboard: (...a) => getDashboard(...a),
  // 케이스별 최고 일치도 막대는 케이스 목록의 per-case progress 를 쓴다
  listCases: (...a) => listCases(...a),
}))
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

/** 케이스 목록 — `progress.best_dice` 가 있는 것만 막대가 된다 */
const CASES = {
  cases: [
    { case_id: 'VS-SEG-202', body_part: 'brain_mri', progress: { best_dice: 1.0, attempts: 2, latest_grade: 'match' } },
    { case_id: 'VS-SEG-204', body_part: 'brain_mri', progress: { best_dice: 0.12, attempts: 1, latest_grade: 'mismatch' } },
    // 아직 풀지 않은 케이스 — 막대로 그리면 0% 로 보여서 "0점"과 구분되지 않는다
    { case_id: 'VS-SEG-207', body_part: 'brain_mri', progress: null },
  ],
}

beforeEach(() => {
  getDashboard.mockReset()
  listCases.mockReset()
  listCases.mockResolvedValue({ cases: [] })
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

  it('지표 대신 **시작할 자리**를 준다 (화면 아래를 백지로 두지 않는다)', async () => {
    getDashboard.mockResolvedValue({
      ...EMPTY,
      has_any_activity: false,
      next_up: { case_id: 'VS-SEG-202', reason: 'not_started' },
    })
    const wrapper = mountView()
    await flushPromises()

    const start = wrapper.find('.start-card')
    expect(start.exists()).toBe(true)
    expect(start.text()).toContain('VS-SEG-202')
  })

  it('기록이 생기면 시작 안내는 사라진다', async () => {
    getDashboard.mockResolvedValue({ ...ACTIVE, has_any_activity: true, next_up: null })
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.start-card').exists()).toBe(false)
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

/**
 * 케이스별 최고 일치도 막대.
 *
 * 이 화면만 답하는 질문("어느 케이스를 덜 맞췄나")이라 넣었다. 대신 지켜야 할 선이 있다:
 * 케이스마다 병변이 달라 **막대끼리는 견줄 수 없고**, 안 푼 케이스를 0% 로 그리면
 * 미시도가 0점으로 보인다.
 */
describe('케이스별 최고 일치도', () => {
  beforeEach(() => {
    getDashboard.mockResolvedValue(ACTIVE)
    listCases.mockResolvedValue(CASES)
  })

  it('낮은 것부터 세우고 값을 막대 옆에 직접 적는다', async () => {
    const wrapper = mountView()
    await flushPromises()

    const names = wrapper.findAll('.bar-name').map((n) => n.text())
    expect(names).toEqual(['VS-SEG-204', 'VS-SEG-202'])
    expect(wrapper.findAll('.bar-value').map((v) => v.text())).toEqual(['12%', '100%'])
  })

  it('**아직 풀지 않은 케이스는 막대로 그리지 않는다** (0% 로 그리면 0점처럼 보인다)', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.findAll('.bar-row')).toHaveLength(2)
    expect(wrapper.find('.bars').text()).not.toContain('VS-SEG-207')
  })

  it('케이스끼리 비교하는 값이 아니라고 화면에 적는다', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.chart-note').text()).toContain('케이스끼리 견주는 값이 아닙니다')
  })

  it('막대가 하나뿐이면 분포가 아니므로 띄우지 않는다', async () => {
    listCases.mockResolvedValue({ cases: [CASES.cases[0], CASES.cases[2]] })
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.chart-card').exists()).toBe(false)
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

// 이 화면은 RouterLink 를 vue-router(목)에서 import 한다 — 전역 stub 이 아니라 그 컴포넌트를 찾는다
const { RouterLink: MockedRouterLink } = await import('vue-router')

describe('raw case_id 비노출', () => {
  const links = (w) => w.findAllComponents(MockedRouterLink).map((l) => String(l.props('to')))

  it('시작 안내·케이스별 막대·최근 기록에 질환이 든 case_id 를 쓰지 않는다', async () => {
    getDashboard.mockResolvedValue({
      ...ACTIVE,
      recent_activity: [{ ...ACTIVE.recent_activity[0], case_id: 'glioma_06' }],
    })
    listCases.mockResolvedValue({
      // 막대는 2개 이상일 때만 그린다
      cases: [
        { ...CASES.cases[0], case_id: 'brain_metastasis_09', disease: 'brain_metastasis' },
        CASES.cases[1],
      ],
    })
    const wrapper = mountView()
    await flushPromises()

    const text = wrapper.text()
    expect(text).not.toContain('glioma')
    expect(text).not.toContain('brain_metastasis')
    expect(text).toContain('케이스 06')
    expect(text).toContain('케이스 09')
    expect(links(wrapper)).toContain('/cases/glioma_06')
    expect(links(wrapper)).toContain('/cases/brain_metastasis_09')
  })

  it('시작 안내 버튼도 중립 라벨을 쓴다', async () => {
    getDashboard.mockResolvedValue({
      ...EMPTY,
      has_any_activity: false,
      next_up: { case_id: 'multiple_sclerosis_15', reason: 'not_started' },
    })
    const wrapper = mountView()
    await flushPromises()

    const start = wrapper.find('.start-card')
    expect(start.text()).toContain('케이스 15 판독하기')
    expect(start.text()).not.toContain('multiple_sclerosis')
    expect(links(wrapper)).toContain('/cases/multiple_sclerosis_15')
  })
})
