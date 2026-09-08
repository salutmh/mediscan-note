/**
 * 계정 설정 — 비밀번호 변경과 회원 탈퇴.
 *
 * 둘 다 **되돌릴 수 없거나 파급이 큰 동작**이라 화면이 함부로 진행하면 안 된다:
 *   - 탈퇴는 무엇이 지워지는지 보여주고 비밀번호를 재확인한다
 *   - 비밀번호 변경은 다른 기기 로그인을 끊으므로 그 사실을 알린다
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const changePassword = vi.fn()
const deleteAccount = vi.fn()
vi.mock('../api/endpoints', () => ({
  changePassword: (...a) => changePassword(...a),
  deleteAccount: (...a) => deleteAccount(...a),
}))

const clearSession = vi.fn()
const replaceToken = vi.fn()
const authState = { token: 'tok', user: { nickname: '테스트', email: 'user@example.com' } }
vi.mock('../stores/auth', () => ({
  authState,
  clearSession: (...a) => clearSession(...a),
  replaceToken: (...a) => replaceToken(...a),
}))

const push = vi.fn()
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))

const AccountView = (await import('./AccountView.vue')).default
const mountView = () => mount(AccountView)

beforeEach(() => {
  ;[changePassword, deleteAccount, clearSession, replaceToken, push].forEach((m) => m.mockReset())
  authState.user = { nickname: '테스트', email: 'user@example.com' }
})

const fillPassword = async (wrapper, { current, next, confirm }) => {
  const inputs = wrapper.findAll('input[type=password]')
  await inputs[0].setValue(current)
  await inputs[1].setValue(next)
  await inputs[2].setValue(confirm)
}

// ---------------------------------------------------------- 비밀번호 변경
describe('비밀번호 변경', () => {
  it('다른 기기 로그인이 끊긴다는 것을 미리 알린다', () => {
    const wrapper = mountView()
    expect(wrapper.text()).toContain('다른 기기의 로그인이 모두 해제됩니다')
  })

  it('새 비밀번호 확인이 다르면 서버를 부르지 않는다', async () => {
    const wrapper = mountView()
    await fillPassword(wrapper, { current: 'current-pw-1', next: 'new-password-1', confirm: 'typo' })
    await wrapper.find('form.confirm').trigger('submit')
    await flushPromises()

    expect(changePassword).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('서로 다릅니다')
  })

  it('너무 짧은 비밀번호는 서버까지 가지 않는다', async () => {
    const wrapper = mountView()
    await fillPassword(wrapper, { current: 'current-pw-1', next: 'short', confirm: 'short' })
    await wrapper.find('form.confirm').trigger('submit')
    await flushPromises()

    expect(changePassword).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('8자 이상')
  })

  it('성공하면 새 토큰으로 갈아끼운다', async () => {
    // 이 기기까지 끊기면 사용자가 곧바로 다시 로그인해야 한다
    changePassword.mockResolvedValue({ password_changed: true, access_token: 'new-token' })

    const wrapper = mountView()
    await fillPassword(wrapper, {
      current: 'current-pw-1',
      next: 'new-password-1',
      confirm: 'new-password-1',
    })
    await wrapper.find('form.confirm').trigger('submit')
    await flushPromises()

    expect(replaceToken).toHaveBeenCalledWith('new-token')
    expect(wrapper.text()).toContain('비밀번호를 변경했습니다')
  })

  it('실패 사유를 그대로 보여준다', async () => {
    changePassword.mockRejectedValue(new Error('현재 비밀번호가 올바르지 않습니다.'))

    const wrapper = mountView()
    await fillPassword(wrapper, {
      current: 'wrong',
      next: 'new-password-1',
      confirm: 'new-password-1',
    })
    await wrapper.find('form.confirm').trigger('submit')
    await flushPromises()

    expect(wrapper.text()).toContain('현재 비밀번호가 올바르지 않습니다')
    expect(replaceToken).not.toHaveBeenCalled()
  })

  it('간편 로그인 계정에는 변경 폼을 보여주지 않는다', () => {
    authState.user = { nickname: 'SNS유저', email: null }
    const wrapper = mountView()
    expect(wrapper.text()).not.toContain('비밀번호 변경')
  })
})

// ------------------------------------------------------------- 회원 탈퇴
describe('회원 탈퇴', () => {
  const startDelete = async (wrapper) => {
    await wrapper.findAll('button').find((b) => b.text() === '탈퇴하기').trigger('click')
  }

  it('무엇이 지워지는지 먼저 보여준다', () => {
    const wrapper = mountView()
    const text = wrapper.text()
    expect(text).toContain('되돌릴 수 없습니다')
    expect(text).toContain('제출·채점 이력')
    expect(text).toContain('학습 기록')
  })

  it('한 번에 삭제되지 않는다 (확인 단계를 거친다)', async () => {
    const wrapper = mountView()
    await startDelete(wrapper)
    await flushPromises()

    // 버튼을 눌러도 바로 지우지 않는다
    expect(deleteAccount).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('비밀번호를 다시 입력')
  })

  it('삭제되면 무엇이 지워졌는지 건수로 보여준다', async () => {
    deleteAccount.mockResolvedValue({
      deleted: true,
      user_id: 'u_1',
      deleted_counts: { consents: 6, submissions: 3, learning_events: 12 },
      deleted_scopes: ['account'],
    })

    const wrapper = mountView()
    await startDelete(wrapper)
    await wrapper.findAll('input[type=password]').at(-1).setValue('current-pw-1')
    await wrapper.findAll('form.confirm').at(-1).trigger('submit')
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('탈퇴가 완료되었습니다')
    expect(text).toContain('제출·채점 이력 3건')
    expect(text).toContain('학습 기록 12건')
    // 계정이 사라졌으므로 로컬만 비운다 (서버 로그아웃을 또 부르면 401 만 온다)
    expect(clearSession).toHaveBeenCalled()
  })
})
