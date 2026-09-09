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

const NETWORK_MESSAGE =
  '서버에 연결하지 못했습니다. 인터넷 연결을 확인한 뒤 다시 시도해 주세요.'

// 개발 빌드에서만 원인을 덧붙인다. 배포 빌드에서는 붙지 않는다.
function devHint(text) {
  return import.meta.env.DEV ? ` (개발 정보: ${text})` : ''
}

function retryAfterMessage(seconds) {
  const wait = seconds >= 60 ? `${Math.ceil(seconds / 60)}분` : `${Math.ceil(seconds)}초`
  return `요청이 너무 잦습니다. ${wait} 후에 다시 시도해 주세요.`
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
  // 서버가 설명을 주지 않은 경우. 사용자가 무엇을 할 수 있는지로 갈라서 말한다 —
  // "HTTP 500" 만 보여주면 다시 시도해도 되는지조차 알 수 없다.
  if (status >= 500) {
    return `서버에 일시적인 문제가 발생했습니다. 잠시 후 다시 시도해 주세요.${devHint(`HTTP ${status}`)}`
  }
  return `요청을 처리하지 못했습니다.${devHint(`HTTP ${status}`)}`
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
    // 이 메시지는 **모든 화면의 모든 요청**이 실패할 때 나온다. 예전에는 여기에
    // "backend 폴더에서 uvicorn ... 이 실행 중인지 확인하세요" 가 들어 있어서,
    // 학습자에게 실행 방법을 안내하고 있었다. 개발자용 힌트는 개발 빌드에만 붙인다.
    throw new ApiError(0, 'NETWORK_ERROR', NETWORK_MESSAGE + devHint(`서버(${BASE})에 연결 실패`))
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
    const code = extractCode(data, res.status)
    let message = extractMessage(data, res.status)
    // 서버는 몇 초 뒤에 풀리는지 알고 있다. "잠시 후" 대신 그 값을 그대로 알려준다.
    if (res.status === 429) {
      const seconds = Number(res.headers.get('Retry-After'))
      if (Number.isFinite(seconds) && seconds > 0) message = retryAfterMessage(seconds)
    }
    throw new ApiError(res.status, code, message)
  }
  return data
}

/**
 * 인증이 필요한 바이너리(이미지 등)를 objectURL 로 받아온다.
 *
 * 검수 시트는 **실제 환자 영상에서 파생된 그림**이라 운영자 인증 뒤에 있다.
 * 그래서 `<img src>` 로 바로 걸 수 없고 (헤더를 붙일 수 없다) blob 으로 받아 쓴다.
 *
 * 반환한 URL 은 쓰고 나면 반드시 `URL.revokeObjectURL` 로 해제한다 —
 * 24장을 오가며 보는 화면이라 안 풀면 메모리에 계속 쌓인다.
 */
export async function fetchObjectUrl(path) {
  const token = getToken()
  const res = await fetch(`${BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) {
    if (res.status === 401) {
      clearToken()
      onUnauthorized?.()
    }
    throw new ApiError(res.status, `HTTP_${res.status}`, '이미지를 불러오지 못했습니다.')
  }
  return URL.createObjectURL(await res.blob())
}

export const api = {
  get: (path, opts) => apiFetch(path, { ...opts, method: 'GET' }),
  post: (path, body, opts) => apiFetch(path, { ...opts, method: 'POST', body }),
  patch: (path, body, opts) => apiFetch(path, { ...opts, method: 'PATCH', body }),
  put: (path, body, opts) => apiFetch(path, { ...opts, method: 'PUT', body }),
  // 본문 없는 DELETE 도 있어서 body 는 선택이다 (회원 탈퇴는 비밀번호를 함께 보낸다)
  delete: (path, body, opts) => apiFetch(path, { ...opts, method: 'DELETE', body }),
}

export { BASE as API_BASE }
