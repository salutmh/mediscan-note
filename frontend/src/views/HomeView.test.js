/**
 * 홈 = 학습 대시보드.
 *
 * **여기서 지키는 것: 없는 값을 만들어내지 않는다.**
 * 한 번도 풀지 않았는데 "0%" 라고 쓰면 "0점을 받았다"로 읽힌다.
 * 그 둘은 완전히 다른 상태다.
 *
 * 그리고 **의료적 판단을 화면에 만들지 않는다.** 여기 나오는 숫자는 전부
 * 사용자 자신의 시도 기록이지, 케이스의 난이도나 소견이 아니다.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const getDashboard = vi.fn()
vi.mock('../api/endpoints', () => ({ getDashboard: (...args) => getDashboard(...args) }))
vi.mock('../stores/auth', () => ({ authState: { user: { nickname: '서연' } } }))

const HomeView = (await import('./HomeView.vue')).default

const RouterLinkStub = { props: ['to'], template: '<a :href="to"><slot /></a>' }
const mountView = () => mount(HomeView, { global: { stubs: { RouterLink: RouterLinkStub } } })

const EMPTY = {
  totals: {
    total_cases: 6,
    gradable_cases: 6,
    matched: 0,
    needs_review: 0,
    attempted: 0,
    not_started: 6,
    total_attempts: 0,
  },
  next_up: {
    case_id: 'VS-SEG-202',
    body_part: 'brain_mri',
    disease: 'vestibular_schwannoma',
    thumbnail_url: 'http://x/thumb.png',
    reason: 'not_started',
  },
  recent_activity: [],
  best_dice: null,
  latest_improvement: null,
  has_any_activity: false,
}

const ACTIVE = {
  ...EMPTY,
  totals: { ...EMPTY.totals, matched: 2, needs_review: 1, attempted: 3, total_attempts: 7 },
  next_up: { ...EMPTY.next_up, reason: 'needs_review' },
  recent_activity: [
    {
      case_id: 'VS-SEG-202',
      grade: 'match',
      dice: 0.91,
      location_score: 96,
      submitted_at: new Date().toISOString(),
      case_active: true,
    },
  ],
  best_dice: 0.91,
  latest_improvement: {
    case_id: 'VS-SEG-202',
    previous_dice: 0.42,
    latest_dice: 0.91,
    delta: 0.49,
    previous_grade: 'mismatch',
    latest_grade: 'match',
    submitted_at: new Date().toISOString(),
  },
  has_any_activity: true,
}

beforeEach(() => {
  getDashboard.mockReset()
})

async function render(data) {
  getDashboard.mockResolvedValue(data)
  const wrapper = mountView()
  await flushPromises()
  return wrapper
}

describe('처음 온 사용자', () => {
  it('아직 기록이 없으면 0% 대신 "기록 없음"이라고 쓴다', async () => {
    // **0% 라고 쓰면 "0점을 받았다"로 읽힌다.** 미시도와 0점은 다른 상태다.
    const text = (await render(EMPTY)).text()
    expect(text).toContain('아직 기록 없음')
    expect(text).not.toContain('최고 일치도 0%')
  })

  it('어디서 시작하면 되는지 알려준다', async () => {
    const text = (await render(EMPTY)).text()
    expect(text).toContain('여기서 시작하세요')
    expect(text).toContain('VS-SEG-202')
    expect(text).toContain('아직 풀지 않은 케이스입니다')
  })

  it('재도전 칸은 비어 있는 이유를 설명한다', async () => {
    expect((await render(EMPTY)).text()).toContain('두 번 이상 풀면')
  })
})

describe('학습 중인 사용자', () => {
  it('복습이 필요하면 그 이유와 함께 복습을 권한다', async () => {
    const text = (await render(ACTIVE)).text()
    expect(text).toContain('이어서 학습하기')
    expect(text).toContain('복습이 필요한 케이스입니다')
    expect(text).toContain('복습하기')
  })

  it('진행 상황을 숫자로 보여준다', async () => {
    const text = (await render(ACTIVE)).text()
    expect(text).toContain('2') // 학습완료
    expect(text).toContain('/ 6')
    expect(text).toContain('91') // 최고 일치도 %
    expect(text).toContain('7') // 총 시도
  })

  it('재도전 개선폭을 이전 → 이번으로 보여준다', async () => {
    const text = (await render(ACTIVE)).text()
    expect(text).toContain('42%')
    expect(text).toContain('91%')
    expect(text).toContain('+49p')
  })

  it('개선폭이 같은 케이스 안의 비교임을 밝힌다', async () => {
    // 케이스마다 병변이 달라서, 서로 다른 케이스의 점수를 비교하면 의미가 없다.
    expect((await render(ACTIVE)).text()).toContain('같은 케이스의 마지막 두 시도')
  })

  it('최근 학습을 시간과 함께 보여준다', async () => {
    const text = (await render(ACTIVE)).text()
    expect(text).toContain('VS-SEG-202')
    expect(text).toContain('일치')
    expect(text).toContain('방금')
  })
})

describe('점수가 내려간 경우', () => {
  it('음수 개선폭을 그대로 보여준다', async () => {
    // **나빠진 것을 숨기지 않는다.** 숨기면 재도전 지표를 믿을 수 없게 된다.
    const worse = {
      ...ACTIVE,
      latest_improvement: {
        ...ACTIVE.latest_improvement,
        previous_dice: 0.9,
        latest_dice: 0.6,
        delta: -0.3,
      },
    }
    expect((await render(worse)).text()).toContain('-30p')
  })
})

describe('실패와 로딩', () => {
  it('불러오는 동안 안내를 보여준다', async () => {
    getDashboard.mockReturnValue(new Promise(() => {}))
    expect(mountView().text()).toContain('불러오는 중')
  })

  it('실패하면 개발자 메시지가 아니라 사람이 읽을 문장을 보여준다', async () => {
    getDashboard.mockRejectedValue(new Error('학습 현황을 불러오지 못했습니다.'))
    const wrapper = mountView()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('불러오지 못했습니다')
    expect(text).not.toContain('/api/')
    expect(text).not.toContain('fetch')
  })
})

describe('의료 내용을 만들지 않는다', () => {
  it('난이도나 소견 같은 의학적 판단을 표시하지 않는다', async () => {
    const text = (await render(ACTIVE)).text()
    for (const forbidden of ['난이도', '소견', '진단', '어려운 케이스', '자주 놓']) {
      expect(text).not.toContain(forbidden)
    }
  })
})
