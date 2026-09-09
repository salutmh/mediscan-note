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

// --- 학습 대시보드 ----------------------------------------------------------
// 홈 화면이 쓰는 요약. **전부 사용자 자신의 제출 이력에서 나온 값이다** —
// 의료적 난이도나 소견은 여기 없다.
export const getDashboard = () => api.get('/me/dashboard')

// --- 2. 케이스 / 판독 -------------------------------------------------------
// 2-1. 케이스 목록
export const listCases = (bodyPart) =>
  api.get(`/cases${bodyPart ? `?body_part=${encodeURIComponent(bodyPart)}` : ''}`)

// 2-2. 케이스 상세
export const getCase = (caseId) => api.get(`/cases/${encodeURIComponent(caseId)}`)

// 2-3. ROI 제출 -> 채점 결과
// duration_seconds 는 **선택**이다. 서버는 없으면 없는 대로 채점한다
// (운영자 화면의 "평균 소요 시간"이 비어 있을 뿐이다).
export const submitRoi = (caseId, roi, durationSeconds) =>
  api.post(`/cases/${encodeURIComponent(caseId)}/submit`, {
    roi,
    ...(durationSeconds == null ? {} : { duration_seconds: durationSeconds }),
  })

// --- 이후 화면용 (5·6) — 아직 화면은 안 만들었지만 계약은 미리 고정 ------------
// 해설이 실제로 화면에 보였을 때 한 번 알린다 (관찰용 — 실패해도 학습 흐름과 무관).
// 같은 (사용자, 케이스) 는 서버가 한 번만 기록한다.
export const markExplanationViewed = (caseId) =>
  api.post(`/cases/${encodeURIComponent(caseId)}/explanation-viewed`)

export const listWrongNotes = () => api.get('/wrong-notes')
export const retryWrongNote = (caseId, roi, durationSeconds) =>
  api.post(`/wrong-notes/${encodeURIComponent(caseId)}/retry`, {
    roi,
    ...(durationSeconds == null ? {} : { duration_seconds: durationSeconds }),
  })
export const analyzeImage = ({ image_base64, region }) => api.post('/analyze', { image_base64, region })
// 2-6-1. 업로드 분석이 지금 가능한지 **미리** 확인 — 사용자가 헛수고하지 않게 한다
export const analyzeAvailability = () => api.get('/analyze/availability')

// 1-4-3. 비밀번호 변경 — 성공하면 **다른 기기 로그인이 전부 끊기고** 새 토큰이 온다.
export const changePassword = ({ current_password, new_password }) =>
  api.post('/auth/password', { current_password, new_password })

// 1-4-4. 비밀번호 재설정 — 운영자에게 받은 일회용 코드로. **로그인 없이 호출한다**
// (비밀번호를 잊은 사람은 로그인할 수 없기 때문이다).
export const resetPassword = ({ email, code, new_password }) =>
  api.post('/auth/password/reset', { email, code, new_password }, { auth: false })

// 1-4-1. 회원 탈퇴 — 되돌릴 수 없다. 이메일 계정은 비밀번호 재확인이 필요하다.
export const deleteAccount = (password) => api.delete('/auth/me', password ? { password } : undefined)

// --- 운영자 API (/api/admin) ------------------------------------------------
// 일반 사용자가 호출하면 403 ADMIN_REQUIRED 가 온다. 화면에서도 숨기지만,
// 실제 차단은 서버가 한다 (프론트 숨김은 UX 이지 권한이 아니다).
export const adminListCases = () => api.get('/admin/cases')
// 학습 지표 — **집계만** 온다 (누가 무엇을 틀렸는지는 나오지 않는다)
export const adminLearningSummary = () => api.get('/admin/learning-summary')
// 비밀번호 재설정 코드 발급 — 코드는 **이 응답에만** 있다 (다시 볼 수 없다)
export const adminIssueResetCode = (email) => api.post('/admin/password-reset', { email })
export const adminGetCase = (caseId) => api.get(`/admin/cases/${encodeURIComponent(caseId)}`)
export const adminUpdateCase = (caseId, patch) =>
  api.patch(`/admin/cases/${encodeURIComponent(caseId)}`, patch)
export const adminSaveFindings = (caseId, findings) =>
  api.put(`/admin/cases/${encodeURIComponent(caseId)}/findings`, findings)
export const adminDeleteFindings = (caseId) =>
  api.delete(`/admin/cases/${encodeURIComponent(caseId)}/findings`)


// --- 케이스 후보 기술 검수 (운영자 전용, 로컬 작업용) ------------------------
// **기술 검수는 의학적 검수가 아니다.** 상태 세 가지의 의미는 app/review_store.py 참고.
export const listReviewCandidates = () => api.get('/admin/review/candidates')
export const getReviewSummary = () => api.get('/admin/review/summary')
export const setTechnicalReview = (caseId, body) =>
  api.put(`/admin/review/candidates/${encodeURIComponent(caseId)}`, body)
// 검수 시트는 인증이 필요해 <img src> 로 직접 부를 수 없다 — blob 으로 받아 objectURL 로 쓴다
export const reviewSheetPath = (caseId) =>
  `/admin/review/candidates/${encodeURIComponent(caseId)}/sheet`
