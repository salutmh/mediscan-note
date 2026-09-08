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
