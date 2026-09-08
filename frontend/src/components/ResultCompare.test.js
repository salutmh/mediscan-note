/**
 * 결과 비교 화면의 **재도전 경과** 표시.
 *
 * 여기서 지키려는 것:
 *   - 첫 시도에는 비교를 만들어내지 않는다 (없는 이전 점수를 0 으로 그리면 "0에서 올랐다"가 된다)
 *   - 서버가 준 값을 그대로 쓴다 (화면에서 다시 계산하면 서버와 어긋난다)
 *   - 못한 시도에만 "지금까지 최고"를 덧붙인다 (잘한 시도에 붙이면 소음이다)
 *
 * jsdom 에는 canvas 구현이 없어 getContext('2d') 가 null 을 돌려준다. 그대로 두면
 * 마운트가 터지는데, 그건 테스트 환경 문제만이 아니다 — 실제 브라우저에서도 컨텍스트
 * 생성은 실패할 수 있고, 그때 **오버레이 하나 때문에 등급·수치까지 사라지면 안 된다**.
 * 컴포넌트가 그 경우를 안내 문구로 넘기도록 고쳤고, 아래 테스트가 그것도 함께 확인한다.
 */
import { describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

import ResultCompare from './ResultCompare.vue'

const BASE_RESULT = {
  grade: 'partial_match',
  dice: 0.55,
  iou: 0.38,
  location_score: 72,
  reference_mask_url: null,
  evaluation: { method: 'reference_mask', is_provisional: false, thresholds: {} },
  spatial_feedback: null,
  ai_prediction: null,
  explanation: null,
}

const mountWith = (progress, overrides = {}) =>
  mount(ResultCompare, {
    props: { result: { ...BASE_RESULT, ...overrides, progress }, submittedMaskDataUrl: null },
  })

describe('재도전 경과', () => {
  it('첫 시도에는 이전 점수를 만들어내지 않는다', () => {
    const wrapper = mountWith({
      attempt_number: 1,
      is_first_attempt: true,
      previous: null,
      best_dice: 0.55,
      improved: null,
    })

    const text = wrapper.text()
    expect(text).toContain('첫 시도')
    expect(text).not.toContain('지난번')
    expect(text).not.toContain('→')
  })

  it('두 번째 시도부터 지난번과 이번을 나란히 보여준다', () => {
    const wrapper = mountWith({
      attempt_number: 2,
      is_first_attempt: false,
      previous: { dice: 0.31, grade: 'mismatch', submitted_at: '2026-09-09T02:00:00+00:00' },
      best_dice: 0.31,
      improved: true,
    })

    const text = wrapper.text()
    expect(text).toContain('2번째 시도')
    expect(text).toContain('0.31')
    expect(text).toContain('0.55')
    expect(text).toContain('기준에 더 가까워졌습니다')
  })

  it('낮아졌을 때 사실대로 말한다', () => {
    const wrapper = mountWith(
      {
        attempt_number: 3,
        is_first_attempt: false,
        previous: { dice: 0.82, grade: 'match', submitted_at: '2026-09-09T02:00:00+00:00' },
        best_dice: 0.82,
        improved: false,
      },
      { dice: 0.4 },
    )

    const text = wrapper.text()
    expect(text).toContain('지난번보다 낮습니다')
    // 못한 시도에는 "여기까지 왔었다"가 도움이 된다
    expect(text).toContain('지금까지 최고')
    expect(text).toContain('0.82')
  })

  it('잘한 시도에는 최고 기록을 덧붙이지 않는다', () => {
    const wrapper = mountWith({
      attempt_number: 2,
      is_first_attempt: false,
      previous: { dice: 0.31, grade: 'mismatch', submitted_at: '2026-09-09T02:00:00+00:00' },
      best_dice: 0.31,
      improved: true,
    })

    expect(wrapper.text()).not.toContain('지금까지 최고')
  })

  it('서버가 progress 를 주지 않으면 아무것도 그리지 않는다', () => {
    // 구버전 서버나 오류 응답에 대비한다. 화면이 깨지면 안 된다.
    const wrapper = mountWith(undefined)
    expect(wrapper.find('.attempt').exists()).toBe(false)
    // 나머지 결과는 그대로 나온다
    expect(wrapper.text()).toContain('0.55')
  })
})


describe('겹쳐보기를 그릴 수 없는 환경', () => {
  it('오버레이가 실패해도 등급과 수치는 그대로 보여준다', async () => {
    // jsdom 에는 canvas 구현이 없어 getContext('2d') 가 null 이다 — 실제로 그 경로를 탄다.
    const wrapper = mountWith({
      attempt_number: 1,
      is_first_attempt: true,
      previous: null,
      best_dice: 0.55,
      improved: null,
    })

    // 안내 문구는 mounted 의 비동기 render 안에서 정해진다
    await flushPromises()

    expect(wrapper.text()).toContain('0.55')
    expect(wrapper.text()).toContain('첫 시도')
    // 왜 그림이 없는지도 알려준다 (빈 자리만 남기지 않는다)
    expect(wrapper.find('.note').text()).toContain('그릴 수 없습니다')
  })
})
