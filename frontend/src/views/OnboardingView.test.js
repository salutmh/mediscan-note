/**
 * 기본정보 설정 (가입 직후 직군 선택).
 *
 * 여기서 지키려는 것
 * ----------------
 *  - **건너뛸 수 있다.** 직군은 학습자 배경일 뿐이고, 여기서 막으면
 *    서비스를 보기도 전에 개인정보부터 내라는 화면이 된다
 *  - **의료 자격을 확인하는 화면이 아니다** — 고른 직군으로 잠기거나 열리는 기능이 없다
 *  - 저장이 실패해도 **들어갈 수 있어야 한다** (프로필 때문에 학습이 막히면 안 된다)
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const updateProfile = vi.fn()
const push = vi.fn()
vi.mock('../api/endpoints', () => ({ updateProfile: (...a) => updateProfile(...a) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))

const OnboardingView = (await import('./OnboardingView.vue')).default

const mountView = () => mount(OnboardingView)
const roleCard = (w, label) => w.findAll('.role').find((b) => b.text().includes(label))

beforeEach(() => {
  updateProfile.mockReset()
  push.mockReset()
  updateProfile.mockResolvedValue({ profile: {} })
})

describe('직군 선택', () => {
  it('시안의 네 가지를 보여준다', async () => {
    const wrapper = mountView()
    const labels = wrapper.findAll('.role-label').map((l) => l.text())
    expect(labels).toEqual(['의대생', '방사선학과 학생', '영상의학과 학생', '간호대생'])
  })

  it('고르면 체크 표시로도 알린다', async () => {
    // **색만으로 구분하지 않는다**
    const wrapper = mountView()
    await roleCard(wrapper, '의대생').trigger('click')

    expect(roleCard(wrapper, '의대생').classes()).toContain('active')
    expect(wrapper.find('.role-check').exists()).toBe(true)
  })

  it('다시 누르면 선택이 풀린다', async () => {
    const wrapper = mountView()
    await roleCard(wrapper, '간호대생').trigger('click')
    await roleCard(wrapper, '간호대생').trigger('click')
    expect(roleCard(wrapper, '간호대생').classes()).not.toContain('active')
  })

  it('고른 값을 코드로 저장하고 홈으로 간다', async () => {
    const wrapper = mountView()
    await roleCard(wrapper, '방사선학과 학생').trigger('click')
    await wrapper.find('.primary').trigger('click')
    await flushPromises()

    // 화면 문구가 아니라 **코드**를 저장한다 (다국어·집계를 생각하면 그쪽이 낫다)
    expect(updateProfile).toHaveBeenCalledWith({ job_role: 'radiology_student' })
    expect(push).toHaveBeenCalledWith({ name: 'home' })
  })
})

describe('건너뛰기', () => {
  it('"나중에 하기"는 아무것도 저장하지 않고 홈으로 보낸다', async () => {
    const wrapper = mountView()
    await wrapper.find('.skip').trigger('click')
    await flushPromises()

    expect(updateProfile).not.toHaveBeenCalled()
    expect(push).toHaveBeenCalledWith({ name: 'home' })
  })

  it('아무것도 고르지 않고 시작해도 막지 않는다', async () => {
    const wrapper = mountView()
    await wrapper.find('.primary').trigger('click')
    await flushPromises()

    expect(updateProfile).not.toHaveBeenCalled()
    expect(push).toHaveBeenCalledWith({ name: 'home' })
  })
})

describe('저장이 실패해도', () => {
  it('학습을 막지 않고 안내만 남긴다', async () => {
    updateProfile.mockRejectedValue(new Error('boom'))
    const wrapper = mountView()
    await roleCard(wrapper, '의대생').trigger('click')
    await wrapper.find('.primary').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('나중에 계정 설정에서 다시 고를 수 있습니다')
  })
})

describe('오해를 막는 문구', () => {
  it('직군으로 잠기는 기능이 없다고 밝힌다', () => {
    // 교육용 서비스에서 "의료인 인증"을 흉내 내는 것이 더 위험하다
    expect(mountView().text()).toContain('잠기거나 열리는 기능은 없습니다')
  })
})
