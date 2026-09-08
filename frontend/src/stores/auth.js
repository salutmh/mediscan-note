/**
 * 로그인 상태 저장소. 지금 규모에서는 Pinia 없이 reactive 하나로 충분하다.
 * 토큰은 localStorage 에 두고(api-spec.md 5절 가이드), 새로고침해도 로그인이 유지되게 한다.
 */
import { computed, reactive } from 'vue'
import { clearToken, getToken, setToken } from '../api/client'

const USER_KEY = 'mediscan.user'

function loadUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) ?? 'null')
  } catch {
    return null
  }
}

export const authState = reactive({
  token: getToken(),
  user: loadUser(),
})

export const isLoggedIn = computed(() => Boolean(authState.token))

/** signup / login / social-login 응답을 그대로 받아 로그인 상태로 만든다. */
export function applyAuthResult(result) {
  setToken(result.access_token)
  authState.token = result.access_token
  authState.user = {
    user_id: result.user_id,
    email: result.email ?? null,
    nickname: result.nickname,
  }
  localStorage.setItem(USER_KEY, JSON.stringify(authState.user))
  return authState.user
}

/**
 * 토큰만 갈아끼운다 (비밀번호 변경 후처럼 세션이 재발급될 때).
 * 사용자 정보는 그대로 두므로 화면이 로그아웃된 것처럼 깜빡이지 않는다.
 */
export function replaceToken(token) {
  setToken(token)
  authState.token = token
}

/** 로컬 상태만 비운다 (401 처리처럼 서버 호출이 무의미한 경우용) */
export function clearSession() {
  clearToken()
  localStorage.removeItem(USER_KEY)
  authState.token = null
  authState.user = null
}

/**
 * 로그아웃 — **서버에 토큰 폐기를 먼저 요청한 뒤** 로컬을 비운다.
 *
 * 서버 호출이 실패해도(네트워크 끊김 등) 로컬은 반드시 비운다. 그래야 이 기기에서는
 * 최소한 로그아웃된 상태가 된다. 다만 그 토큰은 서버에서 아직 유효하므로,
 * 호출 성공 여부를 돌려줘 화면이 필요하면 안내할 수 있게 한다.
 */
export async function logout() {
  let revoked = false
  try {
    // 순환 import 를 피하려고 여기서 가져온다 (endpoints -> client -> stores/auth)
    const { logoutRequest } = await import('../api/endpoints')
    await logoutRequest()
    revoked = true
  } catch {
    revoked = false
  } finally {
    clearSession()
  }
  return revoked
}
