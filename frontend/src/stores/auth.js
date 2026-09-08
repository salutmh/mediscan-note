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

export function logout() {
  clearToken()
  localStorage.removeItem(USER_KEY)
  authState.token = null
  authState.user = null
}
