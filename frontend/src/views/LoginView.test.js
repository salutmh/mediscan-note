/**
 * 화면 0 — 로그인 / 회원가입.
 *
 * 여기서 지키려는 것
 * ----------------
 *  - **필수 동의 없이는 가입 버튼이 눌리지 않는다.** 의료영상(민감정보)을 다루는
 *    서비스라 동의는 법적 요건이고, 화면에서 먼저 막아야 한다
 *  - 가입은 두 단계다 (1 계정 정보 → 2 프로필·학교 + 동의).
 *    1단계에서는 **아직 계정을 만들지 않는다**
 *  - 닉네임만 필수이고 생년월일·학교·전공은 **선택**이다
 *  - 선택 항목 저장이 실패해도 **가입은 유효하다**
 *  - 신규 가입은 기본정보 설정으로, 기존 로그인은 홈으로 간다
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const api = {
  getConsentVersion: vi.fn(),
  login: vi.fn(),
  signup: vi.fn(),
  socialLogin: vi.fn(),
  resetPassword: vi.fn(),
  updateProfile: vi.fn(),
}
vi.mock('../api/endpoints', () => ({
  getConsentVersion: (...a) => api.getConsentVersion(...a),
  login: (...a) => api.login(...a),
  signup: (...a) => api.signup(...a),
  socialLogin: (...a) => api.socialLogin(...a),
  resetPassword: (...a) => api.resetPassword(...a),
  updateProfile: (...a) => api.updateProfile(...a),
}))

const push = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
  useRoute: () => ({ query: {} }),
}))
vi.mock('../stores/auth', () => ({
  applyAuthResult: vi.fn(),
  authState: { token: null, user: null },
}))

const LoginView = (await import('./LoginView.vue')).default

const CONSENT_ITEMS = [
  { key: 'agree_terms', label: '이용약관', required: true },
  { key: 'agree_privacy', label: '개인정보', required: true },
  { key: 'agree_sensitive_data', label: '민감정보', required: true },
  { key: 'agree_ai_notice', label: 'AI 고지', required: true },
  { key: 'agree_age14', label: '만 14세', required: true },
  { key: 'agree_marketing', label: '마케팅', required: false },
]

const AUTH = { user_id: 'u_1', nickname: '테스트', access_token: 't', is_new_user: true }

const mountView = () => mount(LoginView, { global: { stubs: { RouterLink: true } } })

const tab = (w, label) => w.findAll('.segmented button').find((b) => b.text() === label)
const setField = async (w, index, value) => {
  const input = w.findAll('.field input')[index]
  await input.setValue(value)
}
/** jsdom 에서는 submit 버튼 click 이 form submit 을 태우지 않는다 — form 에 직접 건다 */
const submitForm = async (w) => {
  await w.find('form').trigger('submit')
  await flushPromises()
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset())
  push.mockReset()
  api.getConsentVersion.mockResolvedValue({ version: 'v2026-09-01', items: CONSENT_ITEMS })
  api.signup.mockResolvedValue(AUTH)
  api.login.mockResolvedValue({ ...AUTH, is_new_user: undefined })
  api.updateProfile.mockResolvedValue({ profile: {} })
})

async function goToSignupStep2(wrapper) {
  await tab(wrapper, '회원가입').trigger('click')
  await setField(wrapper, 0, 'a@example.com')
  await setField(wrapper, 1, 'pw12345678')
  await submitForm(wrapper)
}

describe('가입 1단계', () => {
  it('이메일·비밀번호만 받고 아직 계정을 만들지 않는다', async () => {
    const wrapper = mountView()
    await flushPromises()
    await tab(wrapper, '회원가입').trigger('click')

    expect(wrapper.find('.submit').text()).toContain('다음')
    expect(wrapper.find('.consents').exists()).toBe(false)

    await setField(wrapper, 0, 'a@example.com')
    await setField(wrapper, 1, 'pw12345678')
    await submitForm(wrapper)

    expect(api.signup).not.toHaveBeenCalled()
  })

  it('비밀번호가 8자 미만이면 다음으로 넘어가지 않는다', async () => {
    const wrapper = mountView()
    await flushPromises()
    await tab(wrapper, '회원가입').trigger('click')
    await setField(wrapper, 0, 'a@example.com')
    await setField(wrapper, 1, 'short')

    expect(wrapper.find('.submit').attributes('disabled')).toBeDefined()
  })
})

describe('가입 2단계', () => {
  it('프로필 항목을 보여주고 **선택**이라고 적는다', async () => {
    const wrapper = mountView()
    await flushPromises()
    await goToSignupStep2(wrapper)

    const labels = wrapper.findAll('.field span').map((s) => s.text())
    expect(labels[0]).toContain('이름')
    expect(labels.join(' ')).toContain('생년월일')
    // 필수처럼 보이면 가입을 망설인다
    expect(wrapper.findAll('.optional').length).toBe(3)
  })

  it('**필수 동의 전에는 가입 버튼이 눌리지 않는다**', async () => {
    const wrapper = mountView()
    await flushPromises()
    await goToSignupStep2(wrapper)

    expect(wrapper.find('.consents').exists()).toBe(true)
    expect(wrapper.find('.submit').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('필수 동의')
  })

  it('이전으로 돌아갈 수 있다', async () => {
    const wrapper = mountView()
    await flushPromises()
    await goToSignupStep2(wrapper)

    await wrapper.findAll('.step-actions button')[0].trigger('click')
    expect(wrapper.find('.submit').text()).toContain('다음')
  })
})

describe('가입 후 이동', () => {
  it('신규 가입은 기본정보 설정으로 간다', async () => {
    const wrapper = mountView()
    await flushPromises()
    await goToSignupStep2(wrapper)

    await wrapper.find('.consents .row.all input').setValue(true)
    await setField(wrapper, 0, '테스트')
    await submitForm(wrapper)

    expect(api.signup).toHaveBeenCalled()
    expect(push).toHaveBeenCalledWith({ name: 'onboarding' })
  })

  it('기존 로그인은 홈으로 간다', async () => {
    const wrapper = mountView()
    await flushPromises()
    await setField(wrapper, 0, 'a@example.com')
    await setField(wrapper, 1, 'pw12345678')
    await submitForm(wrapper)

    expect(push).toHaveBeenCalledWith({ name: 'home' })
  })
})

describe('선택 항목 저장', () => {
  it('학교·전공을 채우면 가입 뒤에 저장한다', async () => {
    const wrapper = mountView()
    await flushPromises()
    await goToSignupStep2(wrapper)

    await wrapper.find('.consents .row.all input').setValue(true)
    await setField(wrapper, 0, '테스트')
    await setField(wrapper, 2, '메드렌즈대학교')
    await submitForm(wrapper)

    expect(api.updateProfile).toHaveBeenCalledWith({ school: '메드렌즈대학교' })
  })

  it('**저장이 실패해도 가입은 유효하다**', async () => {
    // 학교·전공 때문에 방금 만든 계정으로 못 들어가면 안 된다
    api.updateProfile.mockRejectedValue(new Error('boom'))
    const wrapper = mountView()
    await flushPromises()
    await goToSignupStep2(wrapper)

    await wrapper.find('.consents .row.all input').setValue(true)
    await setField(wrapper, 0, '테스트')
    await setField(wrapper, 2, 'A대학교')
    await submitForm(wrapper)

    expect(push).toHaveBeenCalledWith({ name: 'onboarding' })
  })
})
