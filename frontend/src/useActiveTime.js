/**
 * 화면에 실제로 머문 시간 재기.
 *
 * **왜 벽시계 시간을 그대로 쓰지 않는가**
 * 학습자가 케이스를 열어두고 다른 탭으로 가거나 자리를 비우는 일이 흔하다. 그 시간까지
 * 세면 "이 케이스를 푸는 데 얼마나 걸리는가"라는 운영 지표가 몇 시간짜리 값에 끌려간다.
 * 표본이 수십 명인 Closed Beta 에서는 이런 값 하나가 평균을 통째로 망가뜨린다.
 * 그래서 **탭이 숨겨진 동안은 멈춘다.**
 *
 * 이것도 정확한 "집중 시간"은 아니다 — 탭을 띄워둔 채 딴짓하는 것까지는 알 수 없다.
 * 여기서 재는 것은 "이 화면이 보이는 상태로 흐른 시간"이고, 그 이상을 주장하지 않는다.
 */
import { onBeforeUnmount, onMounted } from 'vue'

export function useActiveTime() {
  let accumulated = 0 // 지금까지 쌓인 활성 시간 (ms)
  let startedAt = null // 현재 구간의 시작 시각 (숨김 상태면 null)

  const now = () => Date.now()

  const resume = () => {
    if (startedAt === null) startedAt = now()
  }
  const pause = () => {
    if (startedAt !== null) {
      accumulated += now() - startedAt
      startedAt = null
    }
  }
  const onVisibilityChange = () => {
    document.visibilityState === 'visible' ? resume() : pause()
  }

  /** 다시 0 부터. 케이스를 새로 열거나 재도전을 시작할 때 부른다. */
  const reset = () => {
    accumulated = 0
    startedAt = document.visibilityState === 'visible' ? now() : null
  }

  /** 지금까지의 활성 시간(초). 서버는 정수 초를 받는다. */
  const elapsedSeconds = () => {
    const live = startedAt === null ? 0 : now() - startedAt
    return Math.round((accumulated + live) / 1000)
  }

  onMounted(() => {
    reset()
    document.addEventListener('visibilitychange', onVisibilityChange)
  })
  onBeforeUnmount(() => {
    document.removeEventListener('visibilitychange', onVisibilityChange)
    pause()
  })

  return { reset, elapsedSeconds }
}
