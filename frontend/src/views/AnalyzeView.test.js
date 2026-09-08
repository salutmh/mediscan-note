/**
 * 화면 5 — 내 영상 분석의 준비 상태 처리.
 *
 * 여기서 지키려는 것:
 *   - 사용자가 업로드·ROI·요청을 **다 한 뒤에야** "준비 중"을 만나지 않게 한다
 *   - 준비 상태를 **하드코딩하지 않는다** (모델이 준비되면 반대로 거짓말이 된다)
 *   - 확인에 실패했다고 기능을 잠그지 않는다 (막는 것이 더 나쁘다)
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const analyzeAvailability = vi.fn()
const analyzeImage = vi.fn()
vi.mock('../api/endpoints', () => ({
  analyzeAvailability: (...a) => analyzeAvailability(...a),
  analyzeImage: (...a) => analyzeImage(...a),
}))

const AnalyzeView = (await import('./AnalyzeView.vue')).default

const stubs = {
  RoiCanvas: { props: ['imageUrl', 'disabled'], template: '<div class="roi-stub" />' },
}
const mountView = () => mount(AnalyzeView, { global: { stubs } })

const UNAVAILABLE = {
  body_part: 'brain_mri',
  available: false,
  unavailable_reason: '이 부위 모델은 volume(연속 슬라이스) 입력 전용입니다.',
  is_demo: false,
  disclaimer: '본 결과는 학습 참고용 AI 분석이며 확정 진단이 아닙니다.',
}

beforeEach(() => {
  analyzeAvailability.mockReset()
  analyzeImage.mockReset()
})

describe('분석 준비 상태', () => {
  it('불가능하면 업로드 전에 이유를 알려준다', async () => {
    analyzeAvailability.mockResolvedValue(UNAVAILABLE)

    const wrapper = mountView()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('아직 준비되지 않았습니다')
    // 왜 안 되는지 사실대로 말한다
    expect(text).toContain('volume')
  })

  it('불가능하면 요청 버튼을 막는다', async () => {
    analyzeAvailability.mockResolvedValue(UNAVAILABLE)

    const wrapper = mountView()
    await flushPromises()
    // 요청 카드는 업로드 후에 나타나므로 업로드 상태를 만든다
    wrapper.vm.imageDataUrl = 'data:image/png;base64,x'
    await flushPromises()

    const button = wrapper.findAll('button').find((b) => b.text().includes('분석'))
    expect(button, '요청 버튼을 찾지 못했다').toBeTruthy()
    expect(button.attributes('disabled')).toBeDefined()
    expect(button.text()).toContain('준비 중')
  })

  it('가능하면 준비 중이라고 말하지 않는다', async () => {
    // 상태를 하드코딩하면 모델이 준비된 뒤에 화면이 거짓말을 하게 된다
    analyzeAvailability.mockResolvedValue({ ...UNAVAILABLE, available: true, unavailable_reason: null })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).not.toContain('아직 준비되지 않았습니다')
    expect(wrapper.text()).toContain('AI 분석 결과를 보여드립니다')
  })

  it('상태 확인이 실패해도 화면을 잠그지 않는다', async () => {
    // 확인을 못 했다고 기능을 막으면 더 나쁘다. 서버가 요청 시점에 사실대로 답한다.
    analyzeAvailability.mockRejectedValue(new Error('네트워크 오류'))

    const wrapper = mountView()
    await flushPromises()
    wrapper.vm.imageDataUrl = 'data:image/png;base64,x'
    await flushPromises()

    expect(wrapper.text()).not.toContain('아직 준비되지 않았습니다')
    const button = wrapper.findAll('button').find((b) => b.text().includes('분석'))
    // 입력이 없어 비활성일 수는 있어도 "준비 중"으로 막지는 않는다
    expect(button.text()).not.toContain('준비 중')
  })
})

describe('고지', () => {
  it('확정 진단이 아니라는 문구를 항상 상단에 노출한다', async () => {
    analyzeAvailability.mockResolvedValue(UNAVAILABLE)

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.disclaimer').text()).toContain('확정 진단이 아닙니다')
  })

  it('업로드 영상이 저장되지 않는다는 것을 알린다', async () => {
    analyzeAvailability.mockResolvedValue(UNAVAILABLE)

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('저장되지 않')
  })
})
