/**
 * 화면 2 — 판독 훈련의 핵심 로직.
 *
 * E2E(slice-navigation.mjs)가 실제 브라우저에서 흐름을 보지만, 그건 서버·Chrome 이 다 떠 있어야 한다.
 * 여기서는 **경계 상황**을 빠르게 고정한다:
 *   - slice 가 없는 케이스에서도 화면이 깨지지 않는가
 *   - 대표 slice 밖에서 입력이 잠기는가
 *   - 채점 후 "다음에 무엇을 할지"가 상황에 맞게 나오는가
 *   - 다음 대상 조회가 실패해도 결과 화면이 살아 있는가
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const getCase = vi.fn()
const submitRoi = vi.fn()
const retryWrongNote = vi.fn()
const listCases = vi.fn()
const listWrongNotes = vi.fn()

vi.mock('../api/endpoints', () => ({
  getCase: (...a) => getCase(...a),
  submitRoi: (...a) => submitRoi(...a),
  retryWrongNote: (...a) => retryWrongNote(...a),
  listCases: (...a) => listCases(...a),
  listWrongNotes: (...a) => listWrongNotes(...a),
}))

let routeMeta = {}
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { caseId: 'VS-SEG-202' }, meta: routeMeta }),
  onBeforeRouteUpdate: () => {},
  RouterLink: { props: ['to'], template: '<a><slot /></a>' },
}))

const ReadingView = (await import('./ReadingView.vue')).default

const CASE_WITH_SLICES = {
  case_id: 'VS-SEG-202',
  body_part: 'brain_mri',
  disease: 'vestibular_schwannoma',
  image_url: 'http://x/slice_035.png',
  image_meta: { width: 512, height: 512, slice_index: 35, total_slices: 120 },
  gradable: true,
  representative_slice: 35,
  slices: [
    { slice_index: 34, image_url: 'http://x/slice_034.png' },
    { slice_index: 35, image_url: 'http://x/slice_035.png' },
    { slice_index: 36, image_url: 'http://x/slice_036.png' },
  ],
}

const stubs = {
  RoiCanvas: {
    props: ['imageUrl', 'disabled', 'clearOnImageChange'],
    template:
      '<div class="roi-stub" :data-image="imageUrl" :data-disabled="String(disabled)"' +
      ' :data-clear="String(clearOnImageChange)" />',
  },
  ResultCompare: { props: ['result'], template: '<div class="result-stub" />' },
  ExplanationPanel: { props: ['explanation'], template: '<div class="explanation-stub" />' },
  RouterLink: { props: ['to'], template: '<a><slot /></a>' },
}

const mountView = () => mount(ReadingView, { global: { stubs } })

beforeEach(() => {
  routeMeta = {}
  ;[getCase, submitRoi, retryWrongNote, listCases, listWrongNotes].forEach((m) => m.mockReset())
  getCase.mockResolvedValue(CASE_WITH_SLICES)
  listCases.mockResolvedValue({ cases: [] })
  listWrongNotes.mockResolvedValue({ items: [] })
})

// ------------------------------------------------------------------ slice
describe('slice 탐색', () => {
  it('처음에는 대표 slice 를 보여주고 입력이 열려 있다', async () => {
    const wrapper = mountView()
    await flushPromises()

    const canvas = wrapper.find('.roi-stub')
    expect(canvas.attributes('data-image')).toBe('http://x/slice_035.png')
    expect(canvas.attributes('data-disabled')).toBe('false')
    expect(wrapper.find('.rep-tag').exists()).toBe(true)
  })

  it('slice 를 옮기면 영상이 바뀌고 입력이 잠긴다', async () => {
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.slice-bar input[type=range]').setValue(2) // slice 36
    await flushPromises()

    const canvas = wrapper.find('.roi-stub')
    expect(canvas.attributes('data-image')).toBe('http://x/slice_036.png')
    expect(canvas.attributes('data-disabled')).toBe('true')
    expect(wrapper.find('.slice-locked').exists()).toBe(true)
    expect(wrapper.find('.rep-tag').exists()).toBe(false)
  })

  it('slice 를 넘겨도 캔버스를 비우지 않도록 설정한다', async () => {
    // 이 값이 true 가 되면 옆 slice 를 확인하고 돌아왔을 때 칠하던 ROI 가 사라진다
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.roi-stub').attributes('data-clear')).toBe('false')
  })

  it('slice 가 없는 단일 영상 케이스에서도 화면이 깨지지 않는다', async () => {
    getCase.mockResolvedValue({ ...CASE_WITH_SLICES, slices: [], representative_slice: null })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.slice-bar').exists()).toBe(false)
    // 대표 slice 판정이 없으면 입력은 열려 있어야 한다 (잠기면 아무것도 못 한다)
    expect(wrapper.find('.roi-stub').attributes('data-disabled')).toBe('false')
    expect(wrapper.find('.roi-stub').attributes('data-image')).toBe('http://x/slice_035.png')
  })
})

// --------------------------------------------------------------- 다음 행동
describe('채점 후 다음 행동', () => {
  const GRADED = { case_id: 'VS-SEG-202', grade: 'match', dice: 0.9, explanation: {} }

  const submitOnce = async (wrapper) => {
    // RoiCanvas 를 스텁으로 바꿨으므로 컴포넌트 인스턴스에 직접 주입한다
    wrapper.vm.hasInput = true
    wrapper.vm.roiCanvas = {
      getPoints: () => [[1, 1]],
      getMaskBase64: () => 'data',
      getMaskDataUrl: () => 'data:image/png;base64,x',
      clear: () => {},
    }
    await wrapper.vm.onSubmit()
    await flushPromises()
  }

  it('아직 학습완료가 아닌 케이스를 다음으로 제시한다', async () => {
    submitRoi.mockResolvedValue(GRADED)
    listCases.mockResolvedValue({
      cases: [
        { case_id: 'VS-SEG-202', has_matched: true },
        { case_id: 'VS-SEG-203', has_matched: false },
        { case_id: 'VS-SEG-204', has_matched: false },
      ],
    })

    const wrapper = mountView()
    await flushPromises()
    await submitOnce(wrapper)

    expect(wrapper.vm.nextTarget.caseId).toBe('VS-SEG-203')
    expect(wrapper.vm.nextTarget.remaining).toBe(2)
    expect(wrapper.text()).toContain('다음 케이스')
  })

  it('이미 학습완료한 케이스는 다음으로 제시하지 않는다', async () => {
    submitRoi.mockResolvedValue(GRADED)
    listCases.mockResolvedValue({
      cases: [
        { case_id: 'VS-SEG-202', has_matched: true },
        { case_id: 'VS-SEG-203', has_matched: true },
      ],
    })

    const wrapper = mountView()
    await flushPromises()
    await submitOnce(wrapper)

    expect(wrapper.vm.nextTarget).toBeNull()
    expect(wrapper.text()).toContain('모든 케이스를 학습완료했습니다')
  })

  it('재도전 흐름에서는 남은 복습 케이스를 제시한다', async () => {
    routeMeta = { retry: true }
    retryWrongNote.mockResolvedValue(GRADED)
    listWrongNotes.mockResolvedValue({
      items: [{ case_id: 'VS-SEG-202' }, { case_id: 'VS-SEG-207' }],
    })

    const wrapper = mountView()
    await flushPromises()
    await submitOnce(wrapper)

    // 방금 푼 케이스는 제외된다
    expect(wrapper.vm.nextTarget.caseId).toBe('VS-SEG-207')
    expect(wrapper.text()).toContain('다음 복습 케이스')
    expect(listCases).not.toHaveBeenCalled()
  })

  it('다음 대상 조회가 실패해도 채점 결과는 그대로 보인다', async () => {
    submitRoi.mockResolvedValue(GRADED)
    listCases.mockRejectedValue(new Error('네트워크 오류'))

    const wrapper = mountView()
    await flushPromises()
    await submitOnce(wrapper)

    // 결과는 살아 있고
    expect(wrapper.vm.result).not.toBeNull()
    expect(wrapper.find('.result-stub').exists()).toBe(true)
    // 다음 행동 버튼만 생략된다
    expect(wrapper.vm.nextTarget).toBeNull()
  })
})

// ------------------------------------------------------------------ 경계
describe('경계 상황', () => {
  it('채점 기준이 없는 케이스는 제출을 막는다', async () => {
    getCase.mockResolvedValue({ ...CASE_WITH_SLICES, gradable: false })

    const wrapper = mountView()
    await flushPromises()

    const submit = wrapper.findAll('button').find((b) => b.text().includes('제출'))
    expect(submit.attributes('disabled')).toBeDefined()
  })

  it('케이스를 찾지 못해도 흐름이 막히지 않는다', async () => {
    const err = new Error('없음')
    err.status = 404
    err.name = 'ApiError'
    const { ApiError } = await import('../api/client')
    getCase.mockRejectedValue(Object.assign(new ApiError(404, 'CASE_NOT_FOUND', '없습니다'), {}))

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('찾을 수 없어')
  })
})
