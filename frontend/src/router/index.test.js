/**
 * 라우팅 규칙 — **로그인한 사람이 처음 보는 화면**.
 *
 * 홈(대시보드)을 만들어 놓고도 로그인은 오랫동안 케이스 목록으로 보내고 있었다.
 * "지금 뭘 해야 하는지"를 알려주는 화면을 만들어 두고 아무도 거기로 보내지 않으면
 * 없는 것과 같다. 다시 어긋나지 않게 고정한다.
 */
import { describe, expect, it, beforeEach, vi } from 'vitest'

vi.mock('../stores/auth', () => ({
  authState: { token: null, user: null },
}))

const { authState } = await import('../stores/auth')
const { router } = await import('./index.js')

beforeEach(() => {
  authState.token = null
})

async function goTo(path) {
  await router.push(path).catch(() => {})
  await router.isReady()
  return router.currentRoute.value
}

describe('로그인 뒤 도착하는 화면', () => {
  it('이미 로그인한 사람이 /login 으로 오면 홈으로 보낸다', async () => {
    authState.token = 'token'
    const route = await goTo('/login')
    expect(route.name).toBe('home')
  })

  it('로그인이 필요한 곳에 토큰 없이 가면 로그인으로 보내고 원래 목적지를 기억한다', async () => {
    const route = await goTo('/cases/VS-SEG-202')
    expect(route.name).toBe('login')
    expect(route.query.redirect).toBe('/cases/VS-SEG-202')
  })

  it('홈도 로그인이 필요하다', async () => {
    const route = await goTo('/')
    expect(route.name).toBe('login')
  })
})
