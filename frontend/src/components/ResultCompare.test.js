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


/**
 * **일치했는데 복습 목록에 담긴 경우** (계약 v0.6).
 *
 * 실제로 겪은 일이다: 기준 1,539px 병변에 3,400px(2.2배)을 칠해 정상 조직으로 55% 가
 * 넘친 제출이 Dice 0.62 로 `match` 를 받았다. 화면은 같은 순간 "경계를 조금 더 좁혀
 * 보세요"라고 말하고 있었는데, 학습자는 "기준과 일치"만 보고 끝냈다고 생각했다.
 * 여기서 말해 주지 않으면 복습노트에서 같은 케이스를 다시 만나고 영문을 모른다.
 */
describe('과대 표시 안내', () => {
  const overMarked = (extra = {}) =>
    mount(ResultCompare, {
      props: {
        result: {
          ...BASE_RESULT,
          grade: 'match',
          dice: 0.62,
          review: { needs_review: true, reason: 'over_marked', area_ratio: 2.21, review_area_ratio: 2.0 },
          ...extra,
        },
        submittedMaskDataUrl: null,
      },
    })

  it('몇 배 칠했는지와 복습에 담겼다는 사실을 말한다', () => {
    const text = overMarked().find('.over-marked').text()

    expect(text).toContain('2.2배')
    expect(text).toContain('복습노트에 담았습니다')
  })

  it('**등급을 깎은 것이 아니라는 점**을 함께 밝힌다', () => {
    const wrapper = overMarked()

    // 판정 자체는 그대로 "기준과 일치"로 남는다
    expect(wrapper.find('.grade').text()).toBe('기준과 일치')
    expect(wrapper.find('.over-marked').text()).toContain('판정(기준과 일치)은 그대로입니다')
  })

  it('경계를 잘 맞춘 일치에는 안내가 뜨지 않는다', () => {
    const wrapper = mount(ResultCompare, {
      props: {
        result: {
          ...BASE_RESULT,
          grade: 'match',
          dice: 0.93,
          review: { needs_review: false, reason: null, area_ratio: 1.05, review_area_ratio: 2.0 },
        },
        submittedMaskDataUrl: null,
      },
    })
    expect(wrapper.find('.over-marked').exists()).toBe(false)
  })

  it('review 블록이 없는 응답에서도 깨지지 않는다', () => {
    const wrapper = mount(ResultCompare, {
      props: { result: { ...BASE_RESULT, grade: 'match' }, submittedMaskDataUrl: null },
    })
    expect(wrapper.find('.over-marked').exists()).toBe(false)
  })
})

// ------------------------------------------------------------ 병변 없음 (v0.9)
describe('"병변 없음" 답 / 빈 기준 마스크', () => {
  const metrics = (m) => ({
    source: 'geometry',
    primary_message: m.message,
    items: [{ code: m.code, message: m.message }],
    metrics: {
      gt_coverage: null,
      user_precision: null,
      area_ratio: null,
      centroid_distance_px: null,
      user_area_px: 0,
      reference_area_px: 0,
      ...m.metrics,
    },
  })
  const percents = (wrapper) =>
    wrapper.findAll('.breakdown-value').map((el) => Number.parseInt(el.text(), 10))

  it('기준 마스크 빔 + 병변 없음 -> 기준과 일치 100%, 놓친 0%, 과하게 0%', () => {
    const wrapper = mountWith(null, {
      grade: 'match',
      dice: 1,
      iou: 1,
      location_score: 100,
      answer_type: 'no_abnormality',
      evaluation: { method: 'reference_mask', is_provisional: false, reference_empty: true },
      spatial_feedback: metrics({
        code: 'NO_ABNORMALITY_MATCHED',
        message: '전문가 기준 정답에서도 표시된 병변이 없습니다.',
        metrics: { over_segmentation_ratio: 0, under_segmentation_ratio: 0 },
      }),
    })
    const text = wrapper.text()
    expect(text).toContain('기준과 일치')
    expect(text).toContain('전문가 기준 정답에서도 표시된 병변이 없습니다.')
    expect(wrapper.find('.headline-num').text()).toBe('100')
    expect(percents(wrapper)).toEqual([100, 0, 0])
    // 진단처럼 읽히는 말을 쓰지 않는다
    expect(text).not.toContain('정상')
  })

  it('기준 마스크 빔 + 영역 표시 -> 기준과 다름, 과하게 표시 100%', () => {
    const wrapper = mountWith(null, {
      grade: 'mismatch',
      dice: 0,
      answer_type: 'roi',
      evaluation: { method: 'reference_mask', is_provisional: false, reference_empty: true },
      spatial_feedback: metrics({
        code: 'MARKED_ON_EMPTY_REFERENCE',
        message: '이 학습 케이스의 전문가 기준 마스크에는 표시된 병변이 없는데, 영역을 표시했습니다.',
        metrics: { user_precision: 0, under_segmentation_ratio: 0, user_area_px: 900 },
      }),
    })
    expect(wrapper.text()).toContain('기준과 다름')
    expect(percents(wrapper)).toEqual([0, 0, 100])
  })

  it('기준 마스크 있음 + 병변 없음 -> 기준과 다름, 놓친 부분 100%', () => {
    const wrapper = mountWith(null, {
      grade: 'mismatch',
      dice: 0,
      answer_type: 'no_abnormality',
      evaluation: { method: 'reference_mask', is_provisional: false, reference_empty: false },
      spatial_feedback: metrics({
        code: 'MISSED_REFERENCE',
        message: '전문가 기준 영역을 놓쳤습니다. 이 학습 케이스의 전문가 기준 마스크에는 표시된 병변 영역이 있습니다.',
        metrics: {
          gt_coverage: 0,
          area_ratio: 0,
          over_segmentation_ratio: 0,
          under_segmentation_ratio: 1,
          reference_area_px: 3200,
        },
      }),
    })
    const text = wrapper.text()
    expect(text).toContain('기준과 다름')
    expect(text).toContain('전문가 기준 영역을 놓쳤습니다.')
    expect(percents(wrapper)).toEqual([0, 100, 0])
  })
})
