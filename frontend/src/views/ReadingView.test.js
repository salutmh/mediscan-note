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
    props: ['imageUrl', 'disabled', 'clearOnImageChange', 'tools'],
    // 제출 버튼은 시안 07 처럼 **도구 막대 안**에 있다 (bar-action 슬롯).
    // 슬롯을 그리지 않으면 화면 2 의 제출 자체가 테스트에서 사라진다.
    template:
      '<div class="roi-stub" :data-image="imageUrl" :data-disabled="String(disabled)"' +
      ' :data-clear="String(clearOnImageChange)" :data-tools="tools">' +
      '<slot name="bar-action" /></div>',
  },
  GlossaryPanel: { props: ['disease', 'diseaseLabel'], template: '<div class="glossary-stub" />' },
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

/**
 * 제출하고 나면 **결과가 주인공이다.**
 *
 * 예전에는 제출 뒤에도 판독 캔버스(800px 넘는다)와 옆 칸이 그대로 남아서,
 * 정작 보려고 제출한 결과 비교가 1,700px 아래에 있었다. 이제 캔버스를 접는다 —
 * 다만 **없애지는 않는다**: slice 를 다시 넘겨 보고 싶을 수 있어서 펼칠 수 있게 남긴다.
 */
describe('제출 뒤 판독 캔버스', () => {
  const GRADED = { case_id: 'VS-SEG-202', grade: 'match', dice: 0.9, explanation: {} }

  const submitOnce = async (wrapper) => {
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

  it('제출 전에는 펼쳐져 있고 접는 줄이 없다', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.vm.viewerOpen).toBe(true)
    expect(wrapper.find('.viewer-toggle').exists()).toBe(false)
  })

  it('제출하면 접히고, 다시 펼 수 있는 줄이 생긴다', async () => {
    submitRoi.mockResolvedValue(GRADED)
    listCases.mockResolvedValue({ cases: [] })

    const wrapper = mountView()
    await flushPromises()
    await submitOnce(wrapper)

    expect(wrapper.vm.viewerOpen).toBe(false)
    // **숨기기만 하면 slice 탐색이 사라진 것처럼 보인다.** 펴는 방법이 화면에 있어야 한다
    const toggle = wrapper.find('.viewer-toggle button')
    expect(toggle.exists()).toBe(true)

    await toggle.trigger('click')
    expect(wrapper.vm.viewerOpen).toBe(true)
  })

  it('다시 풀기를 누르면 도로 펼쳐진다', async () => {
    submitRoi.mockResolvedValue(GRADED)
    listCases.mockResolvedValue({ cases: [] })

    const wrapper = mountView()
    await flushPromises()
    await submitOnce(wrapper)
    expect(wrapper.vm.viewerOpen).toBe(false)

    // 제출 뒤 다시 그려지면서 ref 가 새로 바인딩되므로 스텁을 다시 넣는다
    wrapper.vm.roiCanvas = { clear: () => {} }
    wrapper.vm.retry()
    await flushPromises()

    // 접힌 채로 두면 다시 칠할 캔버스가 화면에 없다
    expect(wrapper.vm.viewerOpen).toBe(true)
    expect(wrapper.vm.phase).toBe('idle')
  })

  it('제출 뒤에는 옆 칸(사전·팁)이 사라진다 — 빈 칸을 남기지 않는다', async () => {
    submitRoi.mockResolvedValue(GRADED)
    listCases.mockResolvedValue({ cases: [] })

    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.side').exists()).toBe(true)

    await submitOnce(wrapper)
    expect(wrapper.find('.side').exists()).toBe(false)
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
