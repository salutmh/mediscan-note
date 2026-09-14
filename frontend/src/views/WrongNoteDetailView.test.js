/**
 * 오답 상세 — **다시 풀기 전에 무엇을 놓쳤는지 보는 화면.**
 *
 * 여기서 지키려는 것
 * ----------------
 *  - 제출한 적 없는 케이스는 **정답을 보여주지 않는다** (백엔드가 404 를 주고,
 *    화면은 그 이유를 사람 말로 설명해야 한다 — 개발자 메시지가 아니라)
 *  - 사용자가 칠한 마스크는 저장하지 않으므로 **없다고 밝힌다**
 *    (없는 것을 있는 것처럼 그리지 않는다)
 *  - 숫자는 **내 기록**이지 케이스 난이도가 아니라고 말한다
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const getWrongNoteDetail = vi.fn()
vi.mock('../api/endpoints', () => ({
  getWrongNoteDetail: (...a) => getWrongNoteDetail(...a),
}))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { caseId: 'VS-SEG-203' } }),
  RouterLink: { props: ['to'], template: '<a><slot /></a>' },
}))

const WrongNoteDetailView = (await import('./WrongNoteDetailView.vue')).default

const stubs = {
  RouterLink: { props: ['to'], template: '<a><slot /></a>' },
  ExplanationPanel: { props: ['explanation'], template: '<div class="explanation-stub" />' },
}
const mountView = () => mount(WrongNoteDetailView, { global: { stubs } })

const DETAIL = {
  case_id: 'VS-SEG-203',
  body_part: 'brain_mri',
  disease: 'vestibular_schwannoma',
  image_url: 'http://x/slice.png',
  image_meta: { width: 512, height: 512 },
  reference_mask_url: 'http://x/mask.png',
  latest: {
    grade: 'partial_match',
    dice: 0.3876,
    iou: 0.24,
    location_score: 100,
    attempt_number: 2,
    submitted_at: new Date().toISOString(),
    is_provisional: false,
  },
  attempts: 2,
  best_dice: 0.3876,
  explanation: { content_levels: ['dataset_verified'] },
  user_mask_kept: false,
}

beforeEach(() => {
  getWrongNoteDetail.mockReset()
  getWrongNoteDetail.mockResolvedValue(DETAIL)
})

describe('제출한 적이 있는 케이스', () => {
  it('기준 영역을 영상 위에 겹쳐 보여준다', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(getWrongNoteDetail).toHaveBeenCalledWith('VS-SEG-203')
    const layer = wrapper.find('.layer')
    expect(layer.exists()).toBe(true)
    // 마스크는 **색을 입혀** 얹는다 — 흰 덩어리면 영상의 밝은 부분과 구분되지 않는다
    expect(layer.attributes('style')).toContain('http://x/mask.png')
  })

  it('내 결과를 판정·일치도·시도 횟수로 보여준다', async () => {
    const wrapper = mountView()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('일부 일치')
    expect(text).toContain('39%') // 0.3876 -> 39
    expect(text).toContain('2회')
  })

  it('다시 풀기와 목록으로 두 갈래를 준다', async () => {
    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('.actions a').map((a) => a.text())
    expect(labels).toContain('다시 풀기')
    expect(labels).toContain('목록으로')
  })

  it('해설을 함께 보여준다 — 이게 이 화면의 존재 이유다', async () => {
    // 예전에는 해설이 제출 직후에만 보여서, 복습하러 와도 뭘 틀렸는지 볼 수 없었다
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.explanation-stub').exists()).toBe(true)
  })

  it('내가 칠한 영역은 저장하지 않는다고 밝힌다', async () => {
    // **없는 것을 있는 것처럼 그리지 않는다.**
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('저장하지 않아')
  })

  it('숫자가 케이스 난이도가 아니라고 못 박는다', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('의학적 난이도를 뜻하지 않습니다')
  })
})

describe('아직 제출하지 않은 케이스', () => {
  it('정답을 보여주지 않고 왜 안 되는지 설명한다', async () => {
    // **이 화면의 보안 경계다.** 풀지 않은 케이스의 기준 마스크가 이 경로로 새면 안 된다.
    const err = new Error('아직 제출한 적이 없는 케이스입니다.')
    err.status = 404
    getWrongNoteDetail.mockRejectedValue(err)

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.layer').exists()).toBe(false)
    expect(wrapper.find('.explanation-stub').exists()).toBe(false)
    expect(wrapper.text()).toContain('먼저 한 번 풀어야')
  })

  it('그 밖의 실패는 개발자 메시지가 아니라 사람이 읽을 문장으로 보여준다', async () => {
    getWrongNoteDetail.mockRejectedValue(new Error('서버에 연결하지 못했습니다.'))

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('서버에 연결하지 못했습니다')
    expect(wrapper.text()).not.toContain('undefined')
  })
})
