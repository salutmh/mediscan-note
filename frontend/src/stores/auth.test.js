/**
 * 세션 처리.
 *
 * 여기서 지키려는 것: **로그아웃은 서버에 토큰 폐기를 요청해야 한다.**
 * 브라우저에서만 지우면 공용 PC 에서 그 토큰이 만료(기본 7일)까지 살아 있다.
 * 그리고 서버 호출이 실패해도 **이 기기의 세션은 반드시 비워져야** 한다.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const logoutRequest = vi.fn()
vi.mock('../api/endpoints', () => ({ logoutRequest: (...a) => logoutRequest(...a) }))

const store = await import('./auth')

beforeEach(() => {
  localStorage.clear()
  logoutRequest.mockReset()
  store.authState.token = null
  store.authState.user = null
})

const signIn = () =>
  store.applyAuthResult({
    user_id: 'u_1',
    email: 'user@example.com',
    nickname: '테스트',
    access_token: 'token-abc',
  })

describe('로그인 상태 저장', () => {
  it('로그인하면 토큰과 사용자 정보가 남는다', () => {
    signIn()
    expect(store.authState.token).toBe('token-abc')
    expect(store.authState.user.nickname).toBe('테스트')
    expect(store.isLoggedIn.value).toBe(true)
  })
})

describe('로그아웃', () => {
  it('서버에 토큰 폐기를 요청한다', async () => {
    signIn()
    logoutRequest.mockResolvedValue({ logged_out: true })

    const revoked = await store.logout()

    expect(logoutRequest).toHaveBeenCalledTimes(1)
    expect(revoked).toBe(true)
    expect(store.authState.token).toBeNull()
  })

  it('서버 호출이 실패해도 이 기기의 세션은 비운다', async () => {
    signIn()
    logoutRequest.mockRejectedValue(new Error('네트워크 오류'))

    const revoked = await store.logout()

    // 서버에는 못 닿았다는 사실을 알려준다 (화면이 안내할 수 있어야 한다)
    expect(revoked).toBe(false)
    // 그래도 로컬은 반드시 비워진다
    expect(store.authState.token).toBeNull()
    expect(store.authState.user).toBeNull()
    expect(localStorage.getItem('mediscan.token')).toBeNull()
  })
})

describe('clearSession', () => {
  it('서버를 부르지 않고 로컬만 비운다', () => {
    // 401 핸들러가 쓰는 경로다. 이미 통하지 않는 토큰으로 서버 로그아웃을 부르면
    // 401 이 또 나서 같은 핸들러가 재진입한다.
    signIn()

    store.clearSession()

    expect(logoutRequest).not.toHaveBeenCalled()
    expect(store.authState.token).toBeNull()
    expect(store.isLoggedIn.value).toBe(false)
  })
})
