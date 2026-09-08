/**
 * 모든 API 호출의 공통 진입점.
 *
 * - base URL 은 .env 의 VITE_API_BASE 한 곳에서만 관리한다 (mock -> 실제 API 전환 시 여기만 바꿈).
 * - 토큰이 있으면 자동으로 Authorization: Bearer <token> 헤더를 붙인다.
 *   (api-spec.md 0절 — /api/cases/*, /api/wrong-notes/*, /api/analyze 는 전부 로그인 필요)
 * - 실패 응답은 ApiError 하나로 정규화한다. 백엔드가 FastAPI HTTPException(detail)로 주든
 *   api-spec.md 0절의 {error, code, message} 로 주든 화면에서는 똑같이 다룰 수 있게.
 */
const BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8010/api'
const TOKEN_KEY = 'mediscan.access_token'

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
  }
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

// 401 이 오면 앱이 로그인 화면으로 돌려보낼 수 있도록 훅을 하나 열어둔다 (main.js 에서 등록).
let onUnauthorized = null
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}

function extractCode(data, status) {
  if (data && typeof data === 'object') {
    if (typeof data.code === 'string') return data.code // api-spec.md 공통 에러 포맷
    const d = data.detail
    if (d && typeof d === 'object' && typeof d.code === 'string') return d.code // HTTPException(detail={"code": ...})
  }
  return `HTTP_${status}`
}

function extractMessage(data, status) {
  if (data && typeof data === 'object') {
    if (typeof data.message === 'string') return data.message
    const d = data.detail
    if (typeof d === 'string') return d
    if (d && typeof d === 'object') {
      if (d.code === 'CONSENT_REQUIRED') {
        const missing = Array.isArray(d.missing) ? d.missing.join(', ') : ''
        return `필수 동의가 누락되었습니다${missing ? ` (${missing})` : ''}.`
      }
      if (typeof d.message === 'string') return d.message
    }
    // 422 (pydantic validation) 는 detail 이 배열로 온다
    if (Array.isArray(d) && d.length && d[0]?.msg) return d.map((e) => e.msg).join(', ')
  }
  return `요청이 실패했습니다 (HTTP ${status}).`
}

export async function apiFetch(path, { method = 'GET', body, auth = true, headers = {} } = {}) {
  const finalHeaders = { ...headers }
  if (body !== undefined) finalHeaders['Content-Type'] = 'application/json'

  const token = getToken()
  if (auth && token) finalHeaders.Authorization = `Bearer ${token}`

  let res
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers: finalHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch {
    throw new ApiError(
      0,
      'NETWORK_ERROR',
      `백엔드(${BASE})에 연결할 수 없습니다. backend 폴더에서 uvicorn app.main:app --reload 가 실행 중인지 확인하세요.`,
    )
  }

  const text = await res.text()
  let data = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = null
    }
  }

  if (!res.ok) {
    if (res.status === 401) {
      clearToken()
      onUnauthorized?.()
    }
    throw new ApiError(res.status, extractCode(data, res.status), extractMessage(data, res.status))
  }
  return data
}

export const api = {
  get: (path, opts) => apiFetch(path, { ...opts, method: 'GET' }),
  post: (path, body, opts) => apiFetch(path, { ...opts, method: 'POST', body }),
}

export { BASE as API_BASE }
