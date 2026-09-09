<script setup>
/**
 * 화면 7 — 마이 진행현황 (api-spec.md 4절 화면 7, "선택")
 *
 * **케이스별 학습 이력**을 여기서 본다.
 * 예전에는 `/api/cases` 가 has_matched/needs_review 두 boolean 만 줘서
 * "학습완료율"까지만 그릴 수 있었고, 이 화면은 숫자 네 개와 막대 하나가 전부였다.
 * 지금은 목록 응답에 `progress`(시도 횟수·첫/최근/최고 일치도)가 함께 오므로
 * **처음보다 얼마나 나아졌는지**까지 보여줄 수 있다.
 *
 * 여기 나오는 숫자는 전부 **학습자 자신의 기록**이다.
 * 케이스의 의학적 난이도나 소견을 뜻하지 않으며, 그런 것을 추론하지도 않는다.
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

/** 한 번이라도 푼 케이스만, 최근 시도가 빠른 순으로. */
const history = computed(() =>
  cases.value
    .filter((c) => c.progress)
    .map((c) => {
      const p = c.progress
      const delta =
        p.first_dice != null && p.latest_dice != null
          ? Math.round((p.latest_dice - p.first_dice) * 100)
          : null
      return {
        caseId: c.case_id,
        bodyPart: c.body_part,
        attempts: p.attempts,
        first: percent(p.first_dice),
        latest: percent(p.latest_dice),
        best: percent(p.best_dice),
        // **시도가 한 번뿐이면 변화가 없다.** 0 으로 쓰면 "제자리걸음"으로 읽힌다.
        delta: p.attempts > 1 ? delta : null,
        hasMatched: c.has_matched,
        needsReview: c.needs_review,
        lastAt: p.last_attempt_at,
      }
    })
    .sort((a, b) => (b.lastAt ?? '').localeCompare(a.lastAt ?? '')),
)

/** 여러 번 푼 케이스에서 실제로 나아졌는가 — 재도전이 효과가 있는지 스스로 확인한다. */
const retrySummary = computed(() => {
  const retried = history.value.filter((h) => h.delta != null)
  if (!retried.length) return null
  const improved = retried.filter((h) => h.delta > 0).length
  const total = retried.reduce((sum, h) => sum + h.delta, 0)
  return { retried: retried.length, improved, averageDelta: Math.round(total / retried.length) }
})

const retryTone = computed(() => {
  const summary = retrySummary.value
  if (!summary) return ''
  if (summary.improved === 0) return 'flat'
  return summary.averageDelta >= 0 ? 'up' : 'down'
})

function percent(value) {
  return value == null ? null : Math.round(value * 100)
}

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

    <!-- 케이스별 학습 이력 — **처음보다 얼마나 나아졌는지**가 핵심이다 -->
    <section class="card">
      <div class="card-title">
        <h2>케이스별 학습 이력</h2>
        <span class="muted">최근 시도 순</span>
      </div>

      <!-- **색이 내용과 어긋나면 안 된다.** 0개 개선인데 초록 배경이면
           "잘하고 있다"로 읽힌다. 평균 변화로 톤을 정한다. -->
      <p v-if="retrySummary" class="retry-summary" :class="retryTone">
        다시 푼 케이스 <strong>{{ retrySummary.retried }}개</strong> 중
        <strong>{{ retrySummary.improved }}개</strong>에서 첫 시도보다 기준에 가까워졌습니다
        <span class="muted">(평균 {{ retrySummary.averageDelta >= 0 ? '+' : '' }}{{ retrySummary.averageDelta }}p)</span>
      </p>

      <div v-if="history.length" class="table-wrap">
        <table class="history">
          <thead>
            <tr>
              <th scope="col">케이스</th>
              <th scope="col" class="num">시도</th>
              <th scope="col" class="num">첫 시도</th>
              <th scope="col" class="num">최근</th>
              <th scope="col" class="num">최고</th>
              <th scope="col" class="num">변화</th>
              <th scope="col">상태</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in history" :key="row.caseId">
              <th scope="row">
                <RouterLink :to="`/cases/${row.caseId}`">{{ row.caseId }}</RouterLink>
              </th>
              <td class="num tnum">{{ row.attempts }}</td>
              <td class="num tnum">{{ row.first != null ? row.first + '%' : '—' }}</td>
              <td class="num tnum">{{ row.latest != null ? row.latest + '%' : '—' }}</td>
              <td class="num tnum best">{{ row.best != null ? row.best + '%' : '—' }}</td>
              <td class="num tnum">
                <!-- 시도가 한 번뿐이면 변화가 없다 — 0 이 아니라 빈칸이다 -->
                <span v-if="row.delta == null" class="muted">—</span>
                <span v-else :class="row.delta >= 0 ? 'up' : 'down'">
                  {{ row.delta >= 0 ? '+' : '' }}{{ row.delta }}p
                </span>
              </td>
              <td>
                <span v-if="row.needsReview" class="badge mismatch">복습필요</span>
                <span v-else-if="row.hasMatched" class="badge match">학습완료</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-else class="muted empty-history">
        아직 푼 케이스가 없습니다. 케이스를 풀면 여기에 시도별 기록이 쌓입니다.
      </p>

      <p class="muted foot">
        여기 숫자는 모두 <strong>내가 표시한 영역과 기준 마스크의 일치도</strong>입니다.
        케이스의 의학적 난이도를 뜻하지 않습니다.
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

/* --- 케이스별 학습 이력 ------------------------------------------------ */
.retry-summary {
  margin: 0 0 var(--sp-4);
  padding: var(--sp-3) var(--sp-4);
  background: var(--surface-sunken);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  font-size: 14px;
}
.retry-summary.up {
  background: var(--match-bg);
  border-color: var(--match-line);
}
.retry-summary.down {
  background: var(--partial-bg);
  border-color: var(--partial-line);
}

.table-wrap {
  overflow-x: auto;
}

table.history {
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
}
table.history th,
table.history td {
  padding: 9px var(--sp-3);
  text-align: left;
  border-bottom: 1px solid var(--line);
  white-space: nowrap;
}
table.history thead th {
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-muted);
  border-bottom-width: 1px;
}
table.history .num {
  text-align: right;
}
table.history tbody th {
  font-weight: 600;
}
table.history tbody th a {
  color: var(--ink);
  text-decoration: none;
}
table.history tbody th a:hover {
  color: var(--accent);
  text-decoration: underline;
}
table.history .best {
  color: var(--match-ink);
  font-weight: 600;
}
table.history .up {
  color: var(--match-ink);
  font-weight: 600;
}
table.history .down {
  color: var(--mismatch-ink);
  font-weight: 600;
}
table.history tbody tr:last-child th,
table.history tbody tr:last-child td {
  border-bottom: 0;
}

.empty-history {
  padding: var(--sp-8) 0;
  text-align: center;
}
</style>
