/**
 * ROI 입력 위젯 — **되돌리기**를 중심으로.
 *
 * 왜 이게 중요한가
 * ----------------
 * 예전에는 실수를 되돌릴 방법이 "전체 지우기" 뿐이었다. 마지막 한 획이 틀리면
 * 처음부터 다시 칠해야 했다. 판독 훈련에서 그건 학습이 아니라 노동이다.
 *
 * jsdom 에는 canvas 백엔드가 없다 (`getContext` 가 null 을 준다).
 * `canvas` npm 패키지를 넣으면 되지만 **이 프로젝트는 의존성을 늘리지 않는다** —
 * 대신 최소한의 가짜 2D 컨텍스트를 끼워 넣고 **동작**을 확인한다.
 * 실제로 픽셀이 어떻게 칠해지는지는 브라우저 E2E(`tools/browser-verify/`)가 본다.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const RoiCanvas = (await import('./RoiCanvas.vue')).default

/** 그리기 호출을 받아만 주는 가짜 컨텍스트. */
function fakeContext() {
  const noop = () => {}
  return {
    save: noop, restore: noop, beginPath: noop, moveTo: noop, lineTo: noop,
    stroke: noop, fill: noop, arc: noop, clearRect: noop, fillRect: noop,
    drawImage: noop,
    globalCompositeOperation: '', strokeStyle: '', fillStyle: '',
    lineWidth: 0, lineCap: '', lineJoin: '',
  }
}

let maskSerial = 0

beforeEach(() => {
  maskSerial = 0
  HTMLCanvasElement.prototype.getContext = vi.fn(fakeContext)
  // 스냅샷마다 다른 문자열이 나와야 "어느 시점으로 돌아갔는지" 확인할 수 있다
  HTMLCanvasElement.prototype.toDataURL = vi.fn(
    () => `data:image/png;base64,SNAP${maskSerial++}`,
  )
  // jsdom 의 Image 는 data URL 을 실제로 읽지 않는다 — 즉시 onload 를 부른다
  vi.stubGlobal(
    'Image',
    class {
      set src(value) {
        this._src = value
        queueMicrotask(() => this.onload?.())
      }
      get src() {
        return this._src
      }
    },
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function mountCanvas(props = {}) {
  return mount(RoiCanvas, { props: { width: 64, height: 64, ...props }, attachTo: document.body })
}

/**
 * 캔버스 위에 획 하나를 그린다 (누르고 → 움직이고 → 뗀다).
 *
 * `wrapper.trigger('pointerdown', { clientX })` 는 쓸 수 없다 — jsdom 의
 * MouseEvent 는 `clientX` 가 읽기 전용이라 test-utils 가 값을 넣지 못한다.
 * 생성자에 좌표를 넣어 직접 보낸다.
 */
async function stroke(wrapper, x = 10, y = 10) {
  const el = wrapper.find('canvas').element
  el.setPointerCapture = () => {}
  el.releasePointerCapture = () => {}
  el.getBoundingClientRect = () => ({ left: 0, top: 0, width: 64, height: 64 })

  const fire = (type, clientX, clientY) =>
    el.dispatchEvent(new MouseEvent(type, { clientX, clientY, bubbles: true }))

  fire('pointerdown', x, y)
  fire('pointermove', x + 10, y + 10)
  fire('pointerup', x + 10, y + 10)
  await flushPromises()
}

const undoButton = (w) => w.findAll('.icon')[0]
const redoButton = (w) => w.findAll('.icon')[1]

describe('되돌리기 버튼 상태', () => {
  it('아무것도 그리지 않았으면 둘 다 눌리지 않는다', () => {
    const wrapper = mountCanvas()
    expect(undoButton(wrapper).attributes('disabled')).toBeDefined()
    expect(redoButton(wrapper).attributes('disabled')).toBeDefined()
  })

  it('한 획을 그리면 되돌리기가 열린다', async () => {
    const wrapper = mountCanvas()
    await stroke(wrapper)
    expect(undoButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('되돌린 뒤에는 다시하기가 열린다', async () => {
    const wrapper = mountCanvas()
    await stroke(wrapper)
    await undoButton(wrapper).trigger('click')
    await flushPromises()

    expect(redoButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('입력이 잠겨 있으면 되돌릴 수 없다', async () => {
    // 제출이 끝난 뒤에는 입력이 잠긴다 — 그때 되돌리기가 열려 있으면
    // 제출한 것과 화면이 달라진다.
    const wrapper = mountCanvas({ disabled: true })
    expect(undoButton(wrapper).attributes('disabled')).toBeDefined()
  })
})

describe('되돌리기 동작', () => {
  it('되돌리면 그리기 이전 상태로 돌아간다', async () => {
    const wrapper = mountCanvas()
    await stroke(wrapper)
    expect(wrapper.vm.getPoints().length).toBeGreaterThan(0)

    await undoButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.vm.getPoints()).toEqual([])
  })

  it('다시하기로 되돌린 것을 복구한다', async () => {
    const wrapper = mountCanvas()
    await stroke(wrapper)
    const before = wrapper.vm.getPoints().length

    await undoButton(wrapper).trigger('click')
    await flushPromises()
    await redoButton(wrapper).trigger('click')
    await flushPromises()

    expect(wrapper.vm.getPoints().length).toBe(before)
  })

  it('획 단위로 되돌린다 (픽셀 단위가 아니다)', async () => {
    // 픽셀마다 스냅샷을 쌓으면 되돌리기 한 번이 눈에 띄는 변화를 못 만든다.
    const wrapper = mountCanvas()
    await stroke(wrapper, 10, 10)
    const afterFirst = wrapper.vm.getPoints().length
    await stroke(wrapper, 40, 40)

    await undoButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.vm.getPoints().length).toBe(afterFirst)
  })

  it('되돌린 뒤 새로 그리면 앞의 다시하기 가지는 버린다', async () => {
    // 일반적인 편집기 동작. 안 버리면 "다시하기"가 지금 그림과 무관한 상태로 간다.
    const wrapper = mountCanvas()
    await stroke(wrapper, 10, 10)
    await stroke(wrapper, 40, 40)
    await undoButton(wrapper).trigger('click')
    await flushPromises()

    await stroke(wrapper, 20, 50)
    expect(redoButton(wrapper).attributes('disabled')).toBeDefined()
  })

  it('전체 지우기도 되돌릴 수 있다', async () => {
    // **가장 위험한 버튼이다.** 되돌릴 수 없으면 잘못 눌렀을 때 전부 잃는다.
    const wrapper = mountCanvas()
    await stroke(wrapper)
    const before = wrapper.vm.getPoints().length

    await wrapper.findAll('button').find((b) => b.text() === '전체 지우기').trigger('click')
    await flushPromises()
    expect(wrapper.vm.getPoints()).toEqual([])

    await undoButton(wrapper).trigger('click')
    await flushPromises()
    expect(wrapper.vm.getPoints().length).toBe(before)
  })
})

describe('키보드 단축키', () => {
  it('Ctrl+Z 로 되돌린다', async () => {
    const wrapper = mountCanvas()
    await stroke(wrapper)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true }))
    await flushPromises()
    expect(wrapper.vm.getPoints()).toEqual([])
  })

  it('Ctrl+Shift+Z 로 다시한다', async () => {
    const wrapper = mountCanvas()
    await stroke(wrapper)
    const before = wrapper.vm.getPoints().length

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true }))
    await flushPromises()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, shiftKey: true }))
    await flushPromises()

    expect(wrapper.vm.getPoints().length).toBe(before)
  })

  it('입력이 잠겨 있으면 단축키도 듣지 않는다', async () => {
    const wrapper = mountCanvas()
    await stroke(wrapper)
    const before = wrapper.vm.getPoints().length
    await wrapper.setProps({ disabled: true })

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true }))
    await flushPromises()
    expect(wrapper.vm.getPoints().length).toBe(before)
  })

  it('컴포넌트가 사라지면 단축키 처리도 떼어낸다', async () => {
    // 안 떼면 판독 화면을 떠난 뒤에도 Ctrl+Z 가 붙잡혀 브라우저 기본 동작을 막는다.
    const wrapper = mountCanvas()
    const removeSpy = vi.spyOn(window, 'removeEventListener')
    wrapper.unmount()
    expect(removeSpy).toHaveBeenCalledWith('keydown', expect.any(Function))
  })
})

describe('사용자에게 보이는 오류 문구', () => {
  it('영상을 못 불러와도 서명 URL 을 화면에 뿌리지 않는다', async () => {
    // 서명·만료 파라미터가 그대로 노출되고, 사용자가 할 수 있는 일도 없다.
    const url = 'http://x/static/cases/A/slice.png?e=123&s=abcdef'
    const wrapper = mountCanvas({ imageUrl: url })
    await wrapper.find('img').trigger('error')

    const text = wrapper.text()
    expect(text).toContain('영상을 불러오지 못했습니다')
    expect(text).not.toContain(url)
    expect(text).not.toContain('s=abcdef')
  })
})
