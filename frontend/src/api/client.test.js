/**
 * API 클라이언트의 오류 처리.
 *
 * 이 파일의 메시지는 **모든 화면의 모든 요청**이 실패할 때 사용자가 읽는 문장이다.
 * 여기서 지키려는 것:
 *   - 학습자에게 개발자용 안내(서버 실행 방법, HTTP 코드)를 보여주지 않는다
 *   - 사용자가 다시 시도해도 되는지 알 수 있게 말한다
 *   - 서버가 아는 정보(Retry-After)를 "잠시 후"로 뭉개지 않는다
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiFetch, clearToken, setUnauthorizedHandler } from './client'

const json = (status, body = null, headers = {}) =>
  new Response(body === null ? '' : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  })

beforeEach(() => {
  clearToken()
  setUnauthorizedHandler(null)
})
afterEach(() => {
  vi.unstubAllGlobals()
})

const failWith = async (impl) => {
  vi.stubGlobal('fetch', vi.fn(impl))
  try {
    await apiFetch('/x')
    throw new Error('오류가 나야 하는데 나지 않았다')
  } catch (e) {
    expect(e).toBeInstanceOf(ApiError)
    return e
  }
}

// ------------------------------------------------------------ 네트워크 실패
describe('연결 실패', () => {
  it('학습자에게 서버 실행 방법을 안내하지 않는다', async () => {
    // 예전에는 "backend 폴더에서 uvicorn app.main:app --reload 가 실행 중인지
    // 확인하세요" 가 그대로 나왔다. 이 화면을 보는 사람은 개발자가 아니다.
    const error = await failWith(() => Promise.reject(new TypeError('failed to fetch')))

    expect(error.code).toBe('NETWORK_ERROR')
    expect(error.message).not.toContain('uvicorn')
    expect(error.message).not.toContain('backend 폴더')
    // 대신 사용자가 할 수 있는 것을 말한다
    expect(error.message).toContain('연결')
    expect(error.message).toContain('다시 시도')
  })
})

// ------------------------------------------------------------ 상태코드별
describe('서버 오류', () => {
  it('5xx 는 다시 시도해도 되는 상황임을 알린다', async () => {
    const error = await failWith(() => Promise.resolve(json(503)))
    expect(error.status).toBe(503)
    expect(error.message).toContain('일시적')
    expect(error.message).toContain('다시 시도')
  })

  it('4xx 는 다시 시도하라고 하지 않는다', async () => {
    // 같은 요청을 반복해도 결과가 같다. 되풀이를 권하면 오해를 준다.
    const error = await failWith(() => Promise.resolve(json(400)))
    expect(error.message).not.toContain('다시 시도')
  })

  it('서버가 설명을 주면 그 설명을 그대로 쓴다', async () => {
    const error = await failWith(() =>
      Promise.resolve(json(400, { code: 'CASE_NOT_GRADABLE', message: '기준 마스크가 없습니다.' })),
    )
    expect(error.code).toBe('CASE_NOT_GRADABLE')
    expect(error.message).toBe('기준 마스크가 없습니다.')
  })
})

// ------------------------------------------------------------ 429
describe('요청 수 제한', () => {
  it('Retry-After 를 실제 대기 시간으로 알려준다', async () => {
    // 서버는 몇 초 뒤에 풀리는지 알고 있다. "잠시 후" 로 뭉개면 사용자는 계속 두드린다.
    const error = await failWith(() =>
      Promise.resolve(json(429, { code: 'RATE_LIMITED', message: '잠시 후' }, { 'Retry-After': '45' })),
    )
    expect(error.status).toBe(429)
    expect(error.message).toContain('45초')
  })

  it('오래 기다려야 하면 분 단위로 말한다', async () => {
    const error = await failWith(() =>
      Promise.resolve(json(429, { code: 'RATE_LIMITED' }, { 'Retry-After': '600' })),
    )
    expect(error.message).toContain('10분')
    expect(error.message).not.toContain('600')
  })

  it('Retry-After 가 없으면 서버 문구를 그대로 쓴다', async () => {
    const error = await failWith(() =>
      Promise.resolve(json(429, { code: 'RATE_LIMITED', message: '요청이 너무 잦습니다.' })),
    )
    expect(error.message).toBe('요청이 너무 잦습니다.')
  })
})

// ------------------------------------------------------------ 401
describe('인증 만료', () => {
  it('토큰을 지우고 한 번만 알린다', async () => {
    const onUnauthorized = vi.fn()
    setUnauthorizedHandler(onUnauthorized)

    await failWith(() => Promise.resolve(json(401, { code: 'TOKEN_REVOKED' })))

    expect(onUnauthorized).toHaveBeenCalledTimes(1)
    expect(localStorage.getItem('mediscan.access_token')).toBeNull()
  })
})
