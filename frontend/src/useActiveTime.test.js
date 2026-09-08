/**
 * 화면에 머문 시간 재기.
 *
 * 이 값은 운영자 화면의 "평균 소요 시간"이 된다. 표본이 수십 명인 Closed Beta 에서는
 * 이상치 하나가 평균을 통째로 끌고 가므로, **탭을 열어둔 채 자리를 비운 시간**이
 * 섞이지 않아야 한다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'

import { useActiveTime } from './useActiveTime'

// 컴포저블은 컴포넌트 안에서만 살 수 있다 (onMounted 를 쓴다)
const harness = () => {
  let api = null
  const Host = defineComponent({
    setup() {
      api = useActiveTime()
      return () => null
    },
  })
  const wrapper = mount(Host)
  return { api, wrapper }
}

const setVisibility = (state) => {
  Object.defineProperty(document, 'visibilityState', { value: state, configurable: true })
  document.dispatchEvent(new Event('visibilitychange'))
}

beforeEach(() => {
  vi.useFakeTimers()
  Object.defineProperty(document, 'visibilityState', { value: 'visible', configurable: true })
})
afterEach(() => {
  vi.useRealTimers()
})

describe('머문 시간', () => {
  it('보이는 동안 흐른 시간을 센다', () => {
    const { api } = harness()
    vi.advanceTimersByTime(12_000)
    expect(api.elapsedSeconds()).toBe(12)
  })

  it('탭이 숨겨진 동안은 멈춘다', () => {
    // 케이스를 열어두고 다른 탭에 다녀오는 것은 흔한 일이다.
    // 그 시간까지 세면 "이 케이스를 푸는 데 얼마나 걸리는가" 가 무의미해진다.
    const { api } = harness()
    vi.advanceTimersByTime(5_000)

    setVisibility('hidden')
    vi.advanceTimersByTime(3_600_000) // 한 시간 자리 비움
    setVisibility('visible')

    vi.advanceTimersByTime(4_000)
    expect(api.elapsedSeconds()).toBe(9)
  })

  it('숨겨진 상태에서도 지금까지 쌓인 값은 읽을 수 있다', () => {
    const { api } = harness()
    vi.advanceTimersByTime(7_000)
    setVisibility('hidden')
    vi.advanceTimersByTime(60_000)
    expect(api.elapsedSeconds()).toBe(7)
  })

  it('reset 하면 처음부터 다시 센다', () => {
    // 재도전은 새로운 시도다 — 앞선 시도의 시간을 얹으면 안 된다.
    const { api } = harness()
    vi.advanceTimersByTime(30_000)
    api.reset()
    vi.advanceTimersByTime(4_000)
    expect(api.elapsedSeconds()).toBe(4)
  })

  it('언마운트 후에는 시간이 늘지 않는다', () => {
    const { api, wrapper } = harness()
    vi.advanceTimersByTime(6_000)
    wrapper.unmount()
    vi.advanceTimersByTime(60_000)
    expect(api.elapsedSeconds()).toBe(6)
  })
})
