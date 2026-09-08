<script setup>
/**
 * 화면 7 — 마이 진행현황 (api-spec.md 4절 화면 7, "선택")
 *
 * 화면 정의서에 "별도 집계 엔드포인트 필요 시 추가 논의"로 남아 있어서, 지금은 이미 있는
 * 두 엔드포인트(GET /api/cases, GET /api/wrong-notes)만으로 프론트에서 집계한다.
 *
 * 한계: cases 응답에는 has_matched/needs_review 두 상태만 있어서 "학습완료율"까지만 계산할 수 있다.
 * 기획서의 "부위별 일치율"(일치/부분 일치/불일치 비율)은 제출 이력(Submission)이 필요하므로
 * 집계 엔드포인트가 생겨야 정확히 그릴 수 있다 — 아래 안내 문구로 명시해 두었다.
 */
import { computed, onMounted, ref } from 'vue'
import { listCases, listWrongNotes } from '../api/endpoints'
import { bodyPartLabel } from '../labels'

const cases = ref([])
const wrongNotes = ref([])
const loading = ref(true)
const errorMessage = ref('')

const total = computed(() => cases.value.length)
const solved = computed(() => cases.value.filter((c) => c.has_matched).length)
const solvedRate = computed(() => (total.value ? Math.round((solved.value / total.value) * 100) : 0))

const byBodyPart = computed(() => {
  const map = new Map()
  for (const c of cases.value) {
    const entry = map.get(c.body_part) ?? { bodyPart: c.body_part, total: 0, solved: 0 }
    entry.total += 1
    if (c.has_matched) entry.solved += 1
    map.set(c.body_part, entry)
  }
  return [...map.values()]
    .map((e) => ({ ...e, rate: e.total ? Math.round((e.solved / e.total) * 100) : 0 }))
    .sort((a, b) => b.total - a.total)
})

const wrongCounts = computed(() => ({
  partial_match: wrongNotes.value.filter((i) => i.grade === 'partial_match').length,
  mismatch: wrongNotes.value.filter((i) => i.grade === 'mismatch').length,
}))

// 도넛 게이지용 — 반지름 34, 둘레 = 2πr
const CIRC = 2 * Math.PI * 34
const dash = computed(() => `${(solvedRate.value / 100) * CIRC} ${CIRC}`)

onMounted(async () => {
  try {
    // 두 요청은 서로 의존하지 않으니 병렬로
    const [caseData, wrongData] = await Promise.all([listCases(), listWrongNotes()])
    cases.value = caseData.cases ?? []
    wrongNotes.value = wrongData.items ?? []
  } catch (e) {
    errorMessage.value = e.message
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <header class="head">
    <h1>내 진행현황</h1>
    <p class="lead">지금까지 푼 케이스와 남은 케이스를 한눈에 봅니다.</p>
  </header>

  <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
  <p v-if="loading" class="muted loading">집계 중...</p>

  <template v-else-if="!errorMessage">
    <div class="top">
      <!-- 헤드라인: 해결률 -->
      <section class="card hero">
        <div class="gauge">
          <svg viewBox="0 0 80 80" width="88" height="88" role="img" :aria-label="`학습완료율 ${solvedRate}%`">
            <circle cx="40" cy="40" r="34" fill="none" stroke="var(--gray-100)" stroke-width="9" />
            <circle
              cx="40"
              cy="40"
              r="34"
              fill="none"
              stroke="var(--brand-500)"
              stroke-width="9"
              stroke-linecap="round"
              :stroke-dasharray="dash"
              transform="rotate(-90 40 40)"
            />
          </svg>
          <strong class="gauge-value tnum">{{ solvedRate }}<small>%</small></strong>
        </div>
        <div class="hero-text">
          <span class="tile-label">전체 학습완료율</span>
          <strong class="hero-count tnum">{{ solved }} / {{ total }}</strong>
          <span class="muted">케이스 학습완료 · 남은 {{ total - solved }}건</span>
        </div>
      </section>

      <!-- 복습노트 요약 -->
      <section class="tiles">
        <div class="card tile">
          <span class="tile-label">복습필요 · 부분 일치</span>
          <strong class="tile-value partial_match tnum">{{ wrongCounts.partial_match }}</strong>
        </div>
        <div class="card tile">
          <span class="tile-label">복습필요 · 불일치</span>
          <strong class="tile-value mismatch tnum">{{ wrongCounts.mismatch }}</strong>
        </div>
        <RouterLink to="/wrong-notes" class="card tile link">
          <span class="tile-label">복습하러 가기</span>
          <strong class="go">복습노트 →</strong>
        </RouterLink>
      </section>
    </div>

    <!-- 부위별 진행 -->
    <section class="card bars-card">
      <div class="card-title">
        <h2>부위별 진행</h2>
        <span class="muted">학습완료 / 전체</span>
      </div>

      <p v-if="!byBodyPart.length" class="muted">케이스가 없습니다.</p>
      <ul v-else class="bars">
        <li v-for="row in byBodyPart" :key="row.bodyPart">
          <div class="bar-head">
            <span class="bp">{{ bodyPartLabel(row.bodyPart) }}</span>
            <span class="value tnum">{{ row.solved }} / {{ row.total }} · {{ row.rate }}%</span>
          </div>
          <div class="track" role="img" :aria-label="`${row.bodyPart} 학습완료율 ${row.rate}%`">
            <div class="fill" :style="{ width: row.rate + '%' }"></div>
          </div>
        </li>
      </ul>

      <p class="muted foot">
        <strong>학습완료</strong>는 그 케이스에서 한 번이라도 <strong>일치</strong> 판정을 받은 것을 뜻하며,
        한 번 달성하면 취소되지 않습니다. 이후 다시 틀리면 <strong>복습필요</strong>가 함께 표시됩니다.
      </p>
    </section>
  </template>
</template>

<style scoped>
.head {
  margin-bottom: var(--sp-5);
}

.head h1 {
  margin-bottom: 4px;
}

.loading {
  padding: var(--sp-8) 0;
}

.top {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-4);
  margin-bottom: var(--sp-4);
}

.hero {
  flex: 1 1 300px;
  display: flex;
  align-items: center;
  gap: var(--sp-5);
}

.gauge {
  position: relative;
  flex: 0 0 auto;
  display: grid;
  place-items: center;
}

.gauge svg {
  display: block;
}

.gauge-value {
  position: absolute;
  font-size: 20px;
  font-weight: 700;
  letter-spacing: -0.03em;
}

.gauge-value small {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-muted);
  margin-left: 1px;
}

.hero-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.hero-count {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.2;
}

.tiles {
  flex: 1 1 320px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
  gap: var(--sp-3);
}

.tile {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-4);
}

.tile-label {
  color: var(--ink-muted);
  font-size: 12px;
  font-weight: 500;
}

.tile-value {
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1;
}

.tile-value.partial_match {
  color: var(--partial-ink);
}

.tile-value.mismatch {
  color: var(--mismatch-ink);
}

.tile.link {
  text-decoration: none;
  color: inherit;
  transition: border-color var(--transition), box-shadow var(--transition);
}

.tile.link:hover {
  border-color: var(--brand-300);
  box-shadow: var(--shadow-md);
}

.go {
  color: var(--brand-600);
  font-size: 14px;
}

.bars-card {
  padding: var(--sp-5);
}

.bars {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.bar-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--sp-3);
  margin-bottom: 6px;
}

.bp {
  font-size: 14px;
  font-weight: 500;
}

.value {
  color: var(--ink-muted);
  font-size: 12.5px;
}

/* 진행 바: 단일 색상(파랑) 크기 표현 + 항목마다 직접 레이블 */
.track {
  height: 9px;
  background: var(--gray-100);
  border-radius: var(--r-full);
  overflow: hidden;
}

.fill {
  height: 100%;
  background: var(--brand-500);
  border-radius: 0 4px 4px 0;
  min-width: 2px;
}

.foot {
  margin-top: var(--sp-5);
  padding-top: var(--sp-4);
  border-top: 1px solid var(--line);
  font-size: 12px;
}
</style>
