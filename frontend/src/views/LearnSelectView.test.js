/**
 * 학습 선택 (부위 → 영상 종류 → 질환).
 *
 * 여기서 지키려는 것
 * ----------------
 *  - **없는 콘텐츠를 있는 것처럼 보여주지 않는다.** 준비되지 않은 부위·영상은
 *    누를 수 없고, 그 사실을 **글자로** 쓴다 (색만으로 알리지 않는다).
 *    예전에 5개 부위를 전부 누를 수 있는 탭으로 깔았다가 빈 화면을 네 번 만났다.
 *  - 선택지는 **실제 케이스 목록에서** 만든다 — 화면에 하드코딩하면
 *    케이스가 늘어도 여기만 옛 상태로 남는다
 *  - 부위를 바꾸면 아래 단계는 **다시 고른다** (이전 선택이 남으면 조합이 어긋난다)
 *  - **고를 것이 하나뿐인 단계는 대신 골라 준다.** 선택지가 1개인 버튼을 세 번 누르게
 *    하지 않는다. 둘 이상이면 그대로 사용자가 고른다.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const listCases = vi.fn()
const push = vi.fn()
vi.mock('../api/endpoints', () => ({ listCases: (...a) => listCases(...a) }))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
  RouterLink: { props: ['to'], template: '<a><slot /></a>' },
}))

const LearnSelectView = (await import('./LearnSelectView.vue')).default

const stubs = { RouterLink: { props: ['to'], template: '<a><slot /></a>' } }
const mountView = () => mount(LearnSelectView, { global: { stubs } })

const brainCase = (id) => ({
  case_id: id,
  body_part: 'brain_mri',
  disease: 'vestibular_schwannoma',
})

/** 부위가 둘이면 자동 선택이 걸리지 않는다 — 단계별 동작은 이 픽스처로 본다 */
const TWO_PARTS = {
  cases: [
    brainCase('VS-SEG-202'),
    brainCase('VS-SEG-203'),
    { case_id: 'CXR-1', body_part: 'chest_xray', disease: 'pneumonia' },
  ],
}

const partCard = (w, label) =>
  w.findAll('.pick').find((b) => b.find('.pick-label')?.text() === label)
const modalityCard = (w, code) =>
  w.findAll('.pick.wide-pick').find((b) => b.find('.pick-label')?.text() === code)

beforeEach(() => {
  listCases.mockReset()
  push.mockReset()
  listCases.mockResolvedValue(TWO_PARTS)
})

describe('1단계 — 부위', () => {
  it('케이스가 있는 부위만 누를 수 있고, 나머지는 "준비 중"이라고 쓴다', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(partCard(wrapper, '뇌 MRI').attributes('disabled')).toBeUndefined()
    expect(partCard(wrapper, '뇌 MRI').text()).toContain('2케이스')

    const abdomen = partCard(wrapper, '복부 CT')
    expect(abdomen.attributes('disabled')).toBeDefined()
    // **색만으로 알리지 않는다**
    expect(abdomen.text()).toContain('준비 중')
  })

  it('준비되지 않은 부위를 눌러도 아무 일도 일어나지 않는다', async () => {
    const wrapper = mountView()
    await flushPromises()

    await partCard(wrapper, '복부 CT').trigger('click')
    expect(partCard(wrapper, '복부 CT').classes()).not.toContain('active')
  })
})

describe('2단계 — 영상 종류', () => {
  it('부위를 고르기 전에는 아무것도 고를 수 없다', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('부위를 먼저 고르면')
    expect(modalityCard(wrapper, 'MRI').attributes('disabled')).toBeDefined()
  })

  it('부위가 둘 이상이면 **자동으로 고르지 않는다** — 실제 선택이다', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(partCard(wrapper, '뇌 MRI').classes()).not.toContain('active')
    expect(wrapper.find('.start').attributes('disabled')).toBeDefined()
  })

  it('고른 부위에 딸린 영상 종류만 활성이다', async () => {
    const wrapper = mountView()
    await flushPromises()
    await partCard(wrapper, '뇌 MRI').trigger('click')

    expect(modalityCard(wrapper, 'MRI').attributes('disabled')).toBeUndefined()
    expect(modalityCard(wrapper, 'CT').attributes('disabled')).toBeDefined()
    expect(modalityCard(wrapper, 'CT').text()).toContain('해당 부위에 없음')
  })
})

describe('3단계 — 질환', () => {
  it('질환 목록을 **실제 케이스에서** 만든다', async () => {
    const wrapper = mountView()
    await flushPromises()
    // 부위를 고르면 그 부위의 영상 종류는 하나뿐이라 **자동으로 정해진다**
    await partCard(wrapper, '뇌 MRI').trigger('click')
    expect(modalityCard(wrapper, 'MRI').classes()).toContain('active')

    const chips = wrapper.findAll('.disease-chip').map((c) => c.text())
    expect(chips.join(' ')).toContain('전정신경초종')
  })

  it('질환이 둘 이상이면 **자동으로 고르지 않는다**', async () => {
    listCases.mockResolvedValue({
      cases: [
        brainCase('VS-SEG-202'),
        { case_id: 'MEN-1', body_part: 'brain_mri', disease: 'meningioma' },
        { case_id: 'CXR-1', body_part: 'chest_xray', disease: 'pneumonia' },
      ],
    })
    const wrapper = mountView()
    await flushPromises()
    await partCard(wrapper, '뇌 MRI').trigger('click')

    expect(wrapper.findAll('.disease-chip')).toHaveLength(2)
    expect(wrapper.find('.start').attributes('disabled')).toBeDefined()
  })
})

describe('학습 시작', () => {
  it('세 단계를 다 고르기 전에는 시작할 수 없다', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.start').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('세 단계를 모두 고르면')
  })

  it('나머지 단계에 선택지가 하나뿐이면 부위만 골라도 시작할 수 있다', async () => {
    const wrapper = mountView()
    await flushPromises()
    await partCard(wrapper, '뇌 MRI').trigger('click')

    // 영상 종류·질환이 각각 하나뿐이라 **세 번 누르게 하지 않는다**
    expect(wrapper.find('.start').attributes('disabled')).toBeUndefined()

    // **누르기 전에** 몇 개인지 보인다
    expect(wrapper.find('.start').text()).toContain('2케이스')

    await wrapper.find('.start').trigger('click')
    expect(push).toHaveBeenCalledWith({
      path: '/cases',
      query: { body_part: 'brain_mri', disease: 'vestibular_schwannoma' },
    })
  })

  it('부위를 바꾸면 아래 단계는 다시 고른다', async () => {
    // 이전 선택이 남으면 "뇌 MRI + X-ray" 같은 조합이 만들어진다
    const wrapper = mountView()
    await flushPromises()

    await partCard(wrapper, '뇌 MRI').trigger('click')
    expect(modalityCard(wrapper, 'MRI').classes()).toContain('active')

    await partCard(wrapper, '흉부 X-ray').trigger('click')
    // MRI 선택이 남아 있으면 "흉부 X-ray + MRI" 가 된다
    expect(modalityCard(wrapper, 'MRI').classes()).not.toContain('active')
    // 새 부위에서도 선택지가 하나뿐이면 다시 자동으로 채워진다
    expect(modalityCard(wrapper, 'X-ray').classes()).toContain('active')
  })
})
