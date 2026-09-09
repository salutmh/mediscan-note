/**
 * 운영자 화면 — **운영자가 실수로 학습자에게 영향을 주지 않는가.**
 *
 * 여기서 지키려는 것:
 *   - 고를 수 없는 값을 고를 수 있게 두지 않는다 (고른 뒤에 서버가 실패시키면 늦다)
 *   - 되돌리기 어려운 동작(숨기기)은 확인을 거친다
 *   - 버튼에는 **동작**을 적는다 (상태를 적으면 무엇이 일어날지 모른다)
 *   - 케이스가 늘어도 찾을 수 있다
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const adminListCases = vi.fn()
const adminUpdateCase = vi.fn()
const adminLearningSummary = vi.fn()
const adminSaveFindings = vi.fn()
const adminDeleteFindings = vi.fn()
const adminIssueResetCode = vi.fn()

vi.mock('../api/endpoints', () => ({
  adminListCases: (...a) => adminListCases(...a),
  adminUpdateCase: (...a) => adminUpdateCase(...a),
  adminLearningSummary: (...a) => adminLearningSummary(...a),
  adminSaveFindings: (...a) => adminSaveFindings(...a),
  adminDeleteFindings: (...a) => adminDeleteFindings(...a),
  adminIssueResetCode: (...a) => adminIssueResetCode(...a),
}))

vi.mock('vue-router', () => ({ RouterLink: { template: '<a><slot /></a>' } }))

const AdminCasesView = (await import('./AdminCasesView.vue')).default

const makeCase = (overrides = {}) => ({
  case_id: 'VS-SEG-202',
  body_part: 'brain_mri',
  disease: 'vestibular_schwannoma',
  is_active: true,
  difficulty: null,
  gradable: true,
  submission_count: 332,
  case_findings_status: 'needs_expert_review',
  has_case_findings: false,
  ...overrides,
})

const mountView = async (cases) => {
  adminListCases.mockResolvedValue({ cases })
  adminLearningSummary.mockResolvedValue(null)
  const wrapper = mount(AdminCasesView)
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  ;[
    adminListCases,
    adminUpdateCase,
    adminLearningSummary,
    adminSaveFindings,
    adminDeleteFindings,
    adminIssueResetCode,
  ].forEach((m) => m.mockReset())
})

const rows = (wrapper) => wrapper.findAll('.admin-table tbody tr:not(.editor-row)')
const findButton = (scope, text) =>
  scope.findAll('button').find((b) => b.text().trim() === text)

// ------------------------------------------------ 고를 수 없는 값
describe('검토 상태', () => {
  it('소견이 없으면 "검토 완료" 를 고를 수 없다', async () => {
    // 예전에는 고를 수 있게 해놓고 서버가 422 로 실패시켰다 —
    // 사용자가 고른 뒤에야 안 된다는 것을 알게 되는 구조다.
    const wrapper = await mountView([makeCase({ has_case_findings: false })])

    const approved = wrapper
      .findAll('option')
      .find((o) => o.element.value === 'approved')
    expect(approved.attributes('disabled')).toBeDefined()
    expect(approved.text()).toContain('소견 필요')
  })

  it('무엇을 먼저 해야 하는지 알려준다', async () => {
    const wrapper = await mountView([makeCase({ has_case_findings: false })])
    expect(wrapper.text()).toContain('소견을 먼저 등록')
  })

  it('소견이 있으면 상태를 바꿀 수 없다 (소견과 상태가 어긋나지 않게)', async () => {
    const wrapper = await mountView([
      makeCase({ has_case_findings: true, case_findings_status: 'approved' }),
    ])
    const select = wrapper.findAll('select').at(-1)
    expect(select.attributes('disabled')).toBeDefined()
  })
})

// ------------------------------------------------ 되돌리기 어려운 동작
describe('숨기기', () => {
  it('버튼에 동작을 적는다 (상태가 아니라)', async () => {
    const wrapper = await mountView([makeCase({ is_active: true })])
    expect(findButton(wrapper, '숨기기')).toBeTruthy()
    // 현재 상태는 따로 보여준다
    expect(wrapper.find('.state-tag').text()).toBe('노출 중')
  })

  it('숨겨진 케이스에는 "다시 노출" 이 보인다', async () => {
    const wrapper = await mountView([makeCase({ is_active: false })])
    expect(findButton(wrapper, '다시 노출')).toBeTruthy()
  })

  it('한 번에 숨겨지지 않는다', async () => {
    const wrapper = await mountView([makeCase()])
    await findButton(wrapper, '숨기기').trigger('click')
    await flushPromises()

    expect(adminUpdateCase).not.toHaveBeenCalled()
    expect(wrapper.find('.confirm').exists()).toBe(true)
  })

  it('무엇이 사라지는지와 제출 건수를 알려준다', async () => {
    const wrapper = await mountView([makeCase({ submission_count: 332 })])
    await findButton(wrapper, '숨기기').trigger('click')
    await flushPromises()

    const text = wrapper.find('.confirm').text()
    expect(text).toContain('학습자')
    expect(text).toContain('복습노트')
    expect(text).toContain('332')
  })

  it('취소하면 아무 일도 일어나지 않는다', async () => {
    const wrapper = await mountView([makeCase()])
    await findButton(wrapper, '숨기기').trigger('click')
    await flushPromises()
    await findButton(wrapper, '취소').trigger('click')
    await flushPromises()

    expect(adminUpdateCase).not.toHaveBeenCalled()
    expect(wrapper.find('.confirm').exists()).toBe(false)
  })

  it('확인하면 숨긴다', async () => {
    adminUpdateCase.mockResolvedValue(makeCase({ is_active: false }))
    const wrapper = await mountView([makeCase()])
    await findButton(wrapper, '숨기기').trigger('click')
    await flushPromises()

    const confirm = wrapper.find('.confirm')
    await findButton(confirm, '숨기기').trigger('click')
    await flushPromises()

    expect(adminUpdateCase).toHaveBeenCalledWith('VS-SEG-202', { is_active: false })
  })

  it('다시 노출하는 것은 확인하지 않는다 (되돌리는 방향이라 위험하지 않다)', async () => {
    adminUpdateCase.mockResolvedValue(makeCase({ is_active: true }))
    const wrapper = await mountView([makeCase({ is_active: false })])

    await findButton(wrapper, '다시 노출').trigger('click')
    await flushPromises()

    expect(adminUpdateCase).toHaveBeenCalledWith('VS-SEG-202', { is_active: true })
  })
})

// ------------------------------------------------ 케이스가 늘었을 때
describe('검색과 필터', () => {
  const many = [
    makeCase({ case_id: 'VS-SEG-202' }),
    makeCase({ case_id: 'VS-SEG-018', is_active: false }),
    makeCase({ case_id: 'VS-SEG-077', gradable: false }),
    makeCase({ case_id: 'VS-SEG-141', has_case_findings: true, case_findings_status: 'approved' }),
  ]

  it('케이스 ID 로 찾을 수 있다', async () => {
    const wrapper = await mountView(many)
    expect(rows(wrapper)).toHaveLength(4)

    await wrapper.find('.toolbar input[type=search]').setValue('018')
    expect(rows(wrapper)).toHaveLength(1)
    expect(wrapper.text()).toContain('VS-SEG-018')
  })

  it('숨긴 케이스만 볼 수 있다', async () => {
    const wrapper = await mountView(many)
    await findButton(wrapper, '숨김 1').trigger('click')
    expect(rows(wrapper)).toHaveLength(1)
  })

  it('소견 없는 케이스만 볼 수 있다 (전문가 검토 대상 추리기)', async () => {
    const wrapper = await mountView(many)
    await findButton(wrapper, '소견 없음 3').trigger('click')
    expect(rows(wrapper)).toHaveLength(3)
  })

  it('채점 불가 케이스만 볼 수 있다', async () => {
    const wrapper = await mountView(many)
    await findButton(wrapper, '채점 불가 1').trigger('click')
    expect(rows(wrapper)).toHaveLength(1)
  })

  it('조건에 맞는 케이스가 없으면 그렇다고 말한다', async () => {
    const wrapper = await mountView(many)
    await wrapper.find('.toolbar input[type=search]').setValue('없는케이스')
    expect(rows(wrapper)).toHaveLength(0)
    expect(wrapper.text()).toContain('조건에 맞는 케이스가 없습니다')
  })
})
