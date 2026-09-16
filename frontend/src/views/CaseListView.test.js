/**
 * 화면 1 — 부위 선택과 케이스 목록.
 *
 * 여기서 지키려는 것: **없는 콘텐츠를 있는 것처럼 보여주지 않는다.**
 * 예전에는 계약에 정의된 5개 부위를 모두 **누를 수 있는 탭**으로 깔아뒀는데 실제
 * 케이스는 뇌 MRI 뿐이라, 나머지 4개는 눌러도 빈 목록이었다 — 빈 화면을 네 번 만났다.
 *
 * 지금은 시안 06 처럼 부위를 카드로 보여주되 **준비되지 않은 부위는 누를 수 없다.**
 * 제품이 어디까지 가는지는 보이면서, 빈 화면으로 데려가지는 않는다.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const listCases = vi.fn()
vi.mock('../api/endpoints', () => ({ listCases: (...args) => listCases(...args) }))

const CaseListView = (await import('./CaseListView.vue')).default

const RouterLinkStub = { props: ['to'], template: '<a><slot /></a>' }
const mountView = () =>
  mount(CaseListView, { global: { stubs: { RouterLink: RouterLinkStub } } })

const brainCase = (id) => ({
  case_id: id,
  body_part: 'brain_mri',
  disease: 'vestibular_schwannoma',
  thumbnail_url: `http://x/${id}.png`,
  has_matched: false,
  needs_review: false,
  gradable: true,
})

beforeEach(() => {
  listCases.mockReset()
})

describe('부위 선택 카드', () => {
  const labelsOf = (w) => w.findAll('.part-card .part-label').map((b) => b.text())
  const cardFor = (w, label) =>
    w.findAll('.part-card').find((b) => b.text().includes(label))

  it('고를 수 있는 부위가 둘 이상이면 카드를 깔고, 없는 부위는 **누를 수 없게** 한다', async () => {
    // 예전에는 5개 부위를 전부 누를 수 있는 탭으로 깔아서, 빈 화면을 네 번 만났다.
    // 이제 카드는 보여주되(제품이 어디까지 가는지는 보인다) 빈 화면으로 데려가지 않는다.
    listCases.mockResolvedValue({
      cases: [brainCase('VS-SEG-202'), { ...brainCase('CXR-0001'), body_part: 'chest_xray' }],
    })

    const wrapper = mountView()
    await flushPromises()

    expect(labelsOf(wrapper)).toContain('뇌 MRI')
    expect(labelsOf(wrapper)).toContain('복부 CT')

    expect(cardFor(wrapper, '뇌 MRI').attributes('disabled')).toBeUndefined()
    expect(cardFor(wrapper, '복부 CT').attributes('disabled')).toBeDefined()
    // 준비되지 않은 부위는 **색만이 아니라 글자로도** 알린다
    expect(cardFor(wrapper, '복부 CT').text()).toContain('준비 중')
  })

  it('부위가 하나뿐이면 **카드 줄을 띄우지 않는다** — 고를 것이 없다', async () => {
    // 이 조건이 예전에는 `.some(ready)` 여서, 하나만 준비돼도 참이 됐다.
    // 결과적으로 5칸 중 4칸이 "준비 중"인 줄이 목록 맨 위에 늘 붙어 있었다.
    listCases.mockResolvedValue({ cases: [brainCase('VS-SEG-202'), brainCase('VS-SEG-203')] })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.part-section').exists()).toBe(false)
    expect(wrapper.findAll('.part-card')).toHaveLength(0)
  })

  it('카드를 접어도 **무엇이 있고 무엇이 준비 중인지는 한 줄로 알린다**', async () => {
    listCases.mockResolvedValue({ cases: [brainCase('VS-SEG-202'), brainCase('VS-SEG-203')] })

    const wrapper = mountView()
    await flushPromises()

    const line = wrapper.find('.parts-line')
    expect(line.exists()).toBe(true)
    expect(line.text()).toContain('뇌 MRI')
    expect(line.text()).toContain('2케이스')
    expect(line.text()).toContain('흉부 X-ray')
    expect(line.text()).toContain('준비 중')
  })

  it('부위 카드를 누르면 그 부위로 다시 조회한다', async () => {
    listCases.mockResolvedValue({
      cases: [brainCase('VS-SEG-202'), { ...brainCase('CXR-0001'), body_part: 'chest_xray' }],
    })

    const wrapper = mountView()
    await flushPromises()

    await cardFor(wrapper, '흉부 X-ray').trigger('click')
    await flushPromises()

    expect(listCases).toHaveBeenLastCalledWith('chest_xray')
  })

  it('같은 부위를 다시 누르면 필터가 풀린다', async () => {
    // 고른 것을 되돌릴 방법이 없으면 "전체" 버튼을 따로 찾아야 한다
    listCases.mockResolvedValue({
      cases: [brainCase('VS-SEG-202'), { ...brainCase('CXR-0001'), body_part: 'chest_xray' }],
    })
    const wrapper = mountView()
    await flushPromises()

    await cardFor(wrapper, '흉부 X-ray').trigger('click')
    await flushPromises()
    await cardFor(wrapper, '흉부 X-ray').trigger('click')
    await flushPromises()

    expect(listCases).toHaveBeenLastCalledWith(undefined)
  })

  it('부위를 필터한 뒤에도 카드 목록이 사라지지 않는다', async () => {
    // 필터된 응답으로 카드를 다시 만들면 하나만 남아 다른 부위로 못 돌아간다
    listCases.mockResolvedValueOnce({
      cases: [brainCase('VS-SEG-202'), { ...brainCase('CXR-0001'), body_part: 'chest_xray' }],
    })
    const wrapper = mountView()
    await flushPromises()

    listCases.mockResolvedValueOnce({ cases: [{ ...brainCase('CXR-0001'), body_part: 'chest_xray' }] })
    await cardFor(wrapper, '흉부 X-ray').trigger('click')
    await flushPromises()

    expect(cardFor(wrapper, '뇌 MRI').attributes('disabled')).toBeUndefined()
  })
})

describe('상태 표시', () => {
  it('학습완료와 복습필요는 동시에 표시될 수 있다', async () => {
    // 배타적이지 않다 — 맞힌 뒤 다시 틀리면 둘 다 true 다
    listCases.mockResolvedValue({
      cases: [{ ...brainCase('VS-SEG-202'), has_matched: true, needs_review: true }],
    })

    const wrapper = mountView()
    await flushPromises()

    // **카드 안만 본다.** 페이지 전체 텍스트를 보면 상태 필터 탭의
    // "미시도 0" 라벨에 걸려서, 카드에 뱃지가 없어도 테스트가 실패한다.
    const badges = wrapper.find('.badges').text()
    expect(badges).toContain('학습완료')
    expect(badges).toContain('복습필요')
    expect(badges).not.toContain('미시도')
  })

  it('아무 상태도 아니면 미시도로 보여준다', async () => {
    listCases.mockResolvedValue({ cases: [brainCase('VS-SEG-202')] })

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('미시도')
  })
})

describe('난이도', () => {
  it('전문가가 지정한 난이도만 표시한다', async () => {
    listCases.mockResolvedValue({
      cases: [
        { ...brainCase('VS-SEG-202'), difficulty: 'hard' },
        { ...brainCase('VS-SEG-203'), difficulty: null },
      ],
    })

    const wrapper = mountView()
    await flushPromises()

    const badges = wrapper.findAll('.badge.difficulty').map((b) => b.text())
    // 지정된 것만 뱃지가 붙는다. 미지정은 아무것도 표시하지 않는다
    // ("표시가 없다 = 아직 판정되지 않았다"가 정확한 의미여야 한다)
    expect(badges).toEqual(['어려움'])
  })

  it('난이도가 하나뿐이거나 없으면 필터를 만들지 않는다', async () => {
    listCases.mockResolvedValue({
      cases: [
        { ...brainCase('VS-SEG-202'), difficulty: 'hard' },
        { ...brainCase('VS-SEG-203'), difficulty: null },
      ],
    })

    const wrapper = mountView()
    await flushPromises()

    // 죽은 컨트롤을 만들지 않는다 — 눌러도 결과가 같은 필터는 없느니만 못하다
    expect(wrapper.findAll('.filters').length).toBe(0)
  })

  it('난이도가 여럿이면 필터로 걸러진다', async () => {
    listCases.mockResolvedValue({
      cases: [
        { ...brainCase('VS-SEG-202'), difficulty: 'hard' },
        { ...brainCase('VS-SEG-203'), difficulty: 'easy' },
      ],
    })

    const wrapper = mountView()
    await flushPromises()

    const easyTab = wrapper.findAll('.filters button').find((b) => b.text() === '쉬움')
    await easyTab.trigger('click')

    expect(wrapper.text()).toContain('VS-SEG-203')
    expect(wrapper.text()).not.toContain('VS-SEG-202')
  })
})

describe('실패·빈 상태', () => {
  it('조회가 실패해도 화면이 깨지지 않고 이유를 보여준다', async () => {
    listCases.mockRejectedValue(Object.assign(new Error('백엔드에 연결할 수 없습니다.')))

    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('백엔드에 연결할 수 없습니다.')
  })

  it('케이스가 하나도 없으면 빈 화면 대신 이유를 안내한다', async () => {
    listCases.mockResolvedValue({ cases: [] })

    const wrapper = mountView()
    await flushPromises()

    // 케이스 카드는 없고
    expect(wrapper.findAll('.case-card').length).toBe(0)
    // 대신 빈 상태 안내가 나온다 (아무것도 없는 화면을 보여주지 않는다)
    expect(wrapper.find('.empty').exists()).toBe(true)
    expect(wrapper.text()).toContain('케이스가 없습니다')
  })
})

describe('카드에 학습 진행 상태가 보인다', () => {
  // **데이터는 있는데 화면까지 오지 않던 것.** 목록이 boolean 두 개만 받던
  // 시절에는 카드에 "몇 번 풀었는지"조차 쓸 수 없었다.
  const withProgress = (id, progress, extra = {}) => ({
    ...brainCase(id),
    ...extra,
    progress,
  })

  it('한 번도 풀지 않았으면 0% 가 아니라 "아직 풀지 않았습니다"', async () => {
    // 0% 라고 쓰면 "0점을 받았다"로 읽힌다.
    listCases.mockResolvedValue({ cases: [withProgress('VS-SEG-202', null)] })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).toContain('아직 풀지 않았습니다')
    expect(wrapper.text()).not.toContain('최고 일치도')
  })

  it('시도 횟수와 최고/최근 일치도를 함께 보여준다', async () => {
    listCases.mockResolvedValue({
      cases: [
        withProgress(
          'VS-SEG-202',
          { attempts: 3, best_dice: 0.87, latest_dice: 0.62, latest_grade: 'partial_match' },
          { needs_review: true },
        ),
      ],
    })
    const wrapper = mountView()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('3회 시도')
    expect(text).toContain('87%')
    expect(text).toContain('최근 62%')
  })

  it('행동 문구가 상태에 따라 달라진다', async () => {
    // **상태가 아니라 다음 행동을 쓴다.** "복습필요"는 상태고 "복습하기"는 행동이다.
    listCases.mockResolvedValue({
      cases: [
        withProgress('A', { attempts: 1, best_dice: 0.2 }, { needs_review: true }),
        withProgress('B', { attempts: 1, best_dice: 0.9 }, { has_matched: true }),
        withProgress('C', null),
      ],
    })
    const wrapper = mountView()
    await flushPromises()

    const labels = wrapper.findAll('.go').map((n) => n.text())
    expect(labels).toEqual(['복습하기 →', '다시 풀기 →', '판독하기 →'])
  })

  it('뱃지와 본문이 서로 다른 말을 하지 않는다', async () => {
    // progress 가 없는데 상태 뱃지만 있는 응답(구버전)에서, 본문이
    // "아직 풀지 않았습니다"라고 쓰면 뱃지와 모순된다.
    listCases.mockResolvedValue({
      cases: [withProgress('VS-SEG-202', null, { needs_review: true })],
    })
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.text()).not.toContain('아직 풀지 않았습니다')
  })
})

describe('학습 상태 필터', () => {
  const cases = [
    { ...brainCase('A'), needs_review: true, progress: { attempts: 1, best_dice: 0.1 } },
    { ...brainCase('B'), has_matched: true, progress: { attempts: 2, best_dice: 0.95 } },
    { ...brainCase('C'), progress: null },
  ]

  it('상태별 개수를 탭에 함께 보여준다', async () => {
    listCases.mockResolvedValue({ cases })
    const wrapper = mountView()
    await flushPromises()

    const tabs = wrapper.findAll('.segmented button').map((b) => b.text().replace(/\s+/g, ''))
    expect(tabs).toContain('전체3')
    expect(tabs).toContain('미시도1')
    expect(tabs).toContain('복습필요1')
    expect(tabs).toContain('학습완료1')
  })

  it('복습필요만 고르면 그것만 남는다', async () => {
    listCases.mockResolvedValue({ cases })
    const wrapper = mountView()
    await flushPromises()

    const reviewTab = wrapper.findAll('.segmented button').find((b) => b.text().includes('복습필요'))
    await reviewTab.trigger('click')

    const ids = wrapper.findAll('.case-id').map((n) => n.text())
    expect(ids).toEqual(['A'])
  })

  it('검색어로 케이스를 좁힐 수 있다', async () => {
    listCases.mockResolvedValue({ cases })
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.search input').setValue('b')
    expect(wrapper.findAll('.case-id').map((n) => n.text())).toEqual(['B'])
  })

  it('필터 때문에 비면 되돌릴 방법을 준다', async () => {
    // **막다른 빈 화면을 만들지 않는다.**
    listCases.mockResolvedValue({ cases })
    const wrapper = mountView()
    await flushPromises()

    await wrapper.find('.search input').setValue('없는케이스')
    expect(wrapper.text()).toContain('조건에 맞는 케이스가 없습니다')

    await wrapper.find('.empty button').trigger('click')
    expect(wrapper.findAll('.case-id')).toHaveLength(3)
  })
})
