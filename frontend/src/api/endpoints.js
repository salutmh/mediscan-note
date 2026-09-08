/**
 * docs/api-spec.md 의 엔드포인트를 함수 하나로 1:1 대응시켜 둔 곳.
 * 화면 컴포넌트는 fetch 경로를 직접 알지 않고 여기만 호출한다.
 */
import { api } from './client'

// --- 1. 인증 / 동의 ---------------------------------------------------------
// 1-5. 동의 문구·버전 (로그인 전이므로 auth: false)
export const getConsentVersion = () => api.get('/consents/current-version', { auth: false })

// 1-1. 이메일 회원가입
export const signup = ({ email, password, nickname, consents }) =>
  api.post('/auth/signup', { email, password, nickname, consents }, { auth: false })

// 1-2. 이메일 로그인
export const login = ({ email, password }) => api.post('/auth/login', { email, password }, { auth: false })

// 1-3. SNS 간편가입/로그인 (최초 가입이면 consents 필수)
export const socialLogin = ({ provider, provider_token, consents }) =>
  api.post('/auth/social-login', { provider, provider_token, consents }, { auth: false })

// 1-4. 토큰 유효성 확인
export const getMe = () => api.get('/auth/me')

// 1-4-2. 로그아웃 — **서버에서 이 토큰을 폐기한다.**
// 브라우저에서 지우는 것만으로는 부족하다 (공용 PC 에서 토큰이 만료까지 살아 있으면 안 된다).
export const logoutRequest = () => api.post('/auth/logout')

// --- 2. 케이스 / 판독 -------------------------------------------------------
// 2-1. 케이스 목록
export const listCases = (bodyPart) =>
  api.get(`/cases${bodyPart ? `?body_part=${encodeURIComponent(bodyPart)}` : ''}`)

// 2-2. 케이스 상세
export const getCase = (caseId) => api.get(`/cases/${encodeURIComponent(caseId)}`)

// 2-3. ROI 제출 -> 채점 결과
export const submitRoi = (caseId, roi) => api.post(`/cases/${encodeURIComponent(caseId)}/submit`, { roi })

// --- 이후 화면용 (5·6) — 아직 화면은 안 만들었지만 계약은 미리 고정 ------------
export const listWrongNotes = () => api.get('/wrong-notes')
export const retryWrongNote = (caseId, roi) =>
  api.post(`/wrong-notes/${encodeURIComponent(caseId)}/retry`, { roi })
export const analyzeImage = ({ image_base64, region }) => api.post('/analyze', { image_base64, region })

// 1-4-3. 비밀번호 변경 — 성공하면 **다른 기기 로그인이 전부 끊기고** 새 토큰이 온다.
export const changePassword = ({ current_password, new_password }) =>
  api.post('/auth/password', { current_password, new_password })

// 1-4-1. 회원 탈퇴 — 되돌릴 수 없다. 이메일 계정은 비밀번호 재확인이 필요하다.
export const deleteAccount = (password) => api.delete('/auth/me', password ? { password } : undefined)

// --- 운영자 API (/api/admin) ------------------------------------------------
// 일반 사용자가 호출하면 403 ADMIN_REQUIRED 가 온다. 화면에서도 숨기지만,
// 실제 차단은 서버가 한다 (프론트 숨김은 UX 이지 권한이 아니다).
export const adminListCases = () => api.get('/admin/cases')
// 학습 지표 — **집계만** 온다 (누가 무엇을 틀렸는지는 나오지 않는다)
export const adminLearningSummary = () => api.get('/admin/learning-summary')
export const adminGetCase = (caseId) => api.get(`/admin/cases/${encodeURIComponent(caseId)}`)
export const adminUpdateCase = (caseId, patch) =>
  api.patch(`/admin/cases/${encodeURIComponent(caseId)}`, patch)
export const adminSaveFindings = (caseId, findings) =>
  api.put(`/admin/cases/${encodeURIComponent(caseId)}/findings`, findings)
export const adminDeleteFindings = (caseId) =>
  api.delete(`/admin/cases/${encodeURIComponent(caseId)}/findings`)
