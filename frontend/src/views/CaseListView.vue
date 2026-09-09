<script setup>
/**
 * 화면 1 — 케이스 목록 (api-spec.md 2-1 / 4절 화면 1)
 * 부위 필터 탭 -> GET /api/cases?body_part=... , 카드에 썸네일 + solved 뱃지.
 */
import { computed, onMounted, ref } from 'vue'
import { listCases } from '../api/endpoints'
import { bodyPartLabel, diseaseLabel } from '../labels'
import ScoreBar from '../components/ScoreBar.vue'

const selected = ref('')
const cases = ref([])
const allCases = ref([]) // 필터 탭을 만들기 위한 전체 목록 (부위 필터 없이 한 번 받는다)
const loading = ref(false)
const errorMessage = ref('')

/**
 * 부위 탭은 **실제로 케이스가 있는 부위만** 만든다.
 *
 * 예전에는 계약에 정의된 5개 부위를 모두 탭으로 깔아뒀는데, 지금 등록된 것은 뇌 MRI 뿐이라
 * 나머지 4개는 눌러도 빈 목록이었다. 첫 사용자에게 **있지도 않은 콘텐츠를 있는 것처럼**
 * 보여주는 셈이고, 빈 화면을 네 번 만나게 된다.
 * 다른 부위가 등록되면 자동으로 탭이 생긴다.
 */
const bodyParts = computed(() => {
  const codes = [...new Set(allCases.value.map((c) => c.body_part))].sort()
  const tabs = codes.map((code) => ({ code, label: bodyPartLabel(code) }))
  // 부위가 하나뿐이면 "전체 / 뇌 MRI" 두 탭이 같은 결과라 탭 자체가 의미 없다
  return tabs.length > 1 ? [{ code: '', label: '전체' }, ...tabs] : []
})

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await listCases(selected.value || undefined)
    cases.value = data.cases ?? []
    // 필터가 걸리지 않은 응답일 때만 탭 기준 목록을 갱신한다
    if (!selected.value) allCases.value = cases.value
  } catch (e) {
    errorMessage.value = e.message
    cases.value = []
  } finally {
    loading.value = false
  }
}

function select(code) {
  selected.value = code
  load()
}

onMounted(load)

// 썸네일 파일이 없으면(백엔드에 정적 이미지 미탑재) 깨진 아이콘 대신 빈 어두운 영역을 둔다.
/**
 * 난이도 — **전문가가 지정한 것만** 보여준다.
 * 미지정(null)이면 아무것도 표시하지 않는다. 자동으로 추정해 채우지 않기 때문에
 * "표시가 없다 = 아직 판정되지 않았다"가 정확한 의미다.
 */
const DIFFICULTY_LABEL = { easy: '쉬움', medium: '보통', hard: '어려움' }

/** 난이도 필터. '' 는 전체. */
const difficulty = ref('')
const availableDifficulties = computed(() => {
  const present = new Set(allCases.value.map((c) => c.difficulty).filter(Boolean))
  // 지정된 난이도가 하나도 없으면 필터 자체를 감춘다 (죽은 컨트롤을 만들지 않는다)
  if (present.size < 2) return []
  return ['', 'easy', 'medium', 'hard'].filter((d) => d === '' || present.has(d))
})

/**
 * 학습 상태 필터. 케이스가 늘어나면 "복습필요만 보기"가 가장 자주 쓰인다.
 * 이건 **사용자 자신의 진행 상태**로 거르는 것이지 난이도와 무관하다.
 */
const STATUS_FILTERS = [
  { code: '', label: '전체' },
  { code: 'not_started', label: '미시도' },
  { code: 'needs_review', label: '복습필요' },
  { code: 'matched', label: '학습완료' },
]
const status = ref('')

function statusOf(c) {
  if (c.needs_review) return 'needs_review'
  if (c.has_matched) return 'matched'
  return c.progress ? 'needs_review' : 'not_started'
}

const query = ref('')

const visibleCases = computed(() => {
  let list = cases.value
  if (difficulty.value) list = list.filter((c) => c.difficulty === difficulty.value)
  if (status.value) list = list.filter((c) => statusOf(c) === status.value)
  const q = query.value.trim().toLowerCase()
  if (q) list = list.filter((c) => c.case_id.toLowerCase().includes(q))
  return list
})

const statusCounts = computed(() => {
  const counts = { '': cases.value.length, not_started: 0, needs_review: 0, matched: 0 }
  for (const c of cases.value) counts[statusOf(c)] += 1
  return counts
})

const summary = computed(() => ({
  total: cases.value.length,
  matched: statusCounts.value.matched,
  review: statusCounts.value.needs_review,
}))

/** 카드의 행동 문구 — **상태가 아니라 다음 행동을 쓴다.** */
function actionLabel(c) {
  if (c.needs_review) return '복습하기'
  if (c.has_matched) return '다시 풀기'
  return '판독하기'
}

function percent(value) {
  return value == null ? null : Math.round(value * 100)
}

function onThumbError(event) {
  event.target.style.visibility = 'hidden'
}
</script>

<template>
  <header class="head">
    <div>
      <h1>케이스 목록</h1>
      <p class="lead">
        전문가가 검수한 기준 마스크와 비교하며 판독을 연습합니다.
      </p>
    </div>
    <div v-if="summary.total" class="head-summary">
      <span class="tnum head-num">{{ summary.matched }}</span>
      <span class="head-of">/ {{ summary.total }} 학습완료</span>
    </div>
  </header>

  <div v-if="cases.length" class="toolbar">
    <div class="segmented">
      <button
        v-for="f in STATUS_FILTERS"
        :key="f.code || 'all'"
        :class="{ active: status === f.code }"
        @click="status = f.code"
      >
        {{ f.label }}
        <span class="count">{{ statusCounts[f.code] }}</span>
      </button>
    </div>
    <label class="search">
      <span class="sr-only">케이스 검색</span>
      <input v-model="query" type="search" placeholder="케이스 ID 검색" />
    </label>
  </div>

  <div v-if="availableDifficulties.length" class="segmented filters">
    <button
      v-for="d in availableDifficulties"
      :key="d || 'all'"
      :class="{ active: difficulty === d }"
      @click="difficulty = d"
    >
      {{ d ? DIFFICULTY_LABEL[d] : '전체 난이도' }}
    </button>
  </div>

  <div v-if="bodyParts.length" class="segmented filters">
    <button
      v-for="bp in bodyParts"
      :key="bp.code"
      :class="{ active: selected === bp.code }"
      @click="select(bp.code)"
    >
      {{ bp.label }}
    </button>
  </div>

  <p v-if="errorMessage" class="error">{{ errorMessage }}</p>

  <!-- 로딩 중에는 카드 자리를 미리 잡아둔다 (레이아웃이 튀지 않게) -->
  <ul v-if="loading" class="grid">
    <li v-for="n in 3" :key="n" class="card case-card skeleton">
      <div class="thumb"></div>
      <div class="sk-line"></div>
      <div class="sk-line short"></div>
    </li>
  </ul>

  <div v-else-if="!visibleCases.length && !errorMessage" class="card empty">
    <template v-if="cases.length">
      <p>조건에 맞는 케이스가 없습니다.</p>
      <p class="muted">필터나 검색어를 바꿔 보세요.</p>
      <button class="ghost sm" @click="status = ''; difficulty = ''; query = ''">
        필터 지우기
      </button>
    </template>
    <template v-else>
      <p>해당 부위의 케이스가 없습니다.</p>
      <p class="muted">지금은 뇌 MRI(전정신경초종) 케이스만 등록되어 있습니다.</p>
    </template>
  </div>

  <ul v-else class="grid">
    <li v-for="c in visibleCases" :key="c.case_id">
      <RouterLink :to="{ name: 'reading', params: { caseId: c.case_id } }" class="card case-card">
        <div class="thumb">
          <img :src="c.thumbnail_url" :alt="`${c.case_id} 썸네일`" @error="onThumbError" />
          <span class="badges">
            <span v-if="c.has_matched" class="badge float match">학습완료</span>
            <span v-if="c.needs_review" class="badge float mismatch">복습필요</span>
            <span v-if="!c.has_matched && !c.needs_review" class="badge float">미시도</span>
            <span v-if="c.difficulty" class="badge float difficulty" :class="c.difficulty">
              {{ DIFFICULTY_LABEL[c.difficulty] }}
            </span>
            <span v-if="c.gradable === false" class="badge float dim">채점 준비중</span>
          </span>
        </div>
        <div class="body">
          <strong class="case-id">{{ c.case_id }}</strong>
          <p class="muted meta">
            {{ bodyPartLabel(c.body_part) }}
            <span class="dot">·</span>
            {{ diseaseLabel(c.disease) }}
          </p>

          <!-- **진행 상태.** 한 번도 안 풀었으면 progress 가 null 이고,
               0% 대신 안내 문구를 보여준다 — 0점과 미시도는 다른 상태다. -->
          <div v-if="c.progress" class="progress">
            <div class="progress-top">
              <span class="progress-label">최고 일치도</span>
              <span class="tnum progress-value">{{ percent(c.progress.best_dice) }}%</span>
            </div>
            <ScoreBar
              :value="percent(c.progress.best_dice)"
              :tone="c.has_matched ? 'match' : 'partial_match'"
            />
            <p class="progress-sub">
              {{ c.progress.attempts }}회 시도
              <template v-if="c.progress.latest_dice != null">
                <span class="dot">·</span> 최근 {{ percent(c.progress.latest_dice) }}%
              </template>
            </p>
          </div>
          <!-- progress 가 없는데 상태 뱃지는 붙어 있는 경우가 있다 (구버전 응답).
               그때 "아직 풀지 않았습니다"라고 쓰면 뱃지와 본문이 서로 다른 말을 한다. -->
          <p v-else-if="c.has_matched || c.needs_review" class="progress-empty">
            시도 기록을 불러오지 못했습니다
          </p>
          <p v-else class="progress-empty">아직 풀지 않았습니다</p>
        </div>
        <span class="go">{{ actionLabel(c) }} →</span>
      </RouterLink>
    </li>
  </ul>
</template>

<style scoped>
.head {
  margin-bottom: var(--sp-5);
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--sp-4);
  flex-wrap: wrap;
}

.head-summary {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.head-num {
  font-size: 26px;
  font-weight: 700;
}
.head-of {
  color: var(--ink-muted);
  font-size: 13.5px;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  margin-bottom: var(--sp-5);
  flex-wrap: wrap;
}
.toolbar .count {
  margin-left: 5px;
  font-variant-numeric: tabular-nums;
  opacity: 0.65;
  font-size: 12px;
}
.search input {
  width: 220px;
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  font: inherit;
  background: var(--surface);
}
.search input:focus-visible {
  outline: 2px solid var(--brand-300);
  outline-offset: 1px;
  border-color: var(--brand-300);
}

.progress {
  margin-top: var(--sp-3);
}
.progress-top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 5px;
}
.progress-label {
  font-size: 12px;
  color: var(--ink-muted);
}
.progress-value {
  font-size: 14px;
  font-weight: 700;
}
.progress-sub {
  margin: 5px 0 0;
  font-size: 12px;
  color: var(--ink-muted);
}
.progress-empty {
  margin: var(--sp-3) 0 0;
  font-size: 12.5px;
  color: var(--ink-muted);
}

.head h1 {
  margin-bottom: 4px;
}

.filters {
  margin-bottom: var(--sp-5);
}

.grid {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: var(--sp-4);
}

.case-card {
  display: block;
  padding: 0;
  overflow: hidden;
  text-decoration: none;
  color: inherit;
  transition: transform var(--transition), box-shadow var(--transition), border-color var(--transition);
}

a.case-card:hover {
  transform: translateY(-2px);
  border-color: var(--brand-300);
  box-shadow: var(--shadow-md);
}

.thumb {
  position: relative;
  aspect-ratio: 1;
  background: var(--viewer-bg);
  display: grid;
  place-items: center;
}

.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.badges {
  position: absolute;
  top: 10px;
  right: 10px;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}

.badge.float {
  background: rgba(13, 17, 23, 0.72);
  border-color: rgba(255, 255, 255, 0.16);
  color: #e7ecf3;
  backdrop-filter: blur(4px);
}

.badge.float.match {
  background: var(--match-bg);
  border-color: var(--match-line);
  color: var(--match-ink);
}

.badge.float.mismatch {
  background: var(--mismatch-bg);
  border-color: var(--mismatch-line);
  color: var(--mismatch-ink);
}

/* 난이도 — 상태(학습완료/복습필요)와 색이 겹치지 않게 중립 톤을 쓴다.
   난이도는 성취가 아니라 케이스의 성질이므로 초록/빨강으로 물들이지 않는다. */
.badge.float.difficulty {
  background: rgba(13, 17, 23, 0.72);
  border-color: rgba(255, 255, 255, 0.28);
  color: #e7ecf3;
  font-weight: 600;
}

.badge.float.difficulty.hard {
  border-color: rgba(255, 255, 255, 0.5);
}

.badge.float.dim {
  opacity: 0.85;
}

.body {
  padding: var(--sp-4) var(--sp-4) 0;
}

.case-id {
  font-size: 14.5px;
  letter-spacing: -0.02em;
}

.meta {
  margin-top: 2px;
}

.dot {
  color: var(--gray-300);
  margin: 0 2px;
}

.go {
  display: block;
  padding: var(--sp-3) var(--sp-4) var(--sp-4);
  color: var(--brand-600);
  font-size: 13px;
  font-weight: 600;
}

.empty {
  text-align: center;
  padding: var(--sp-10) var(--sp-5);
}

.empty p:first-child {
  font-weight: 600;
  margin-bottom: 4px;
}

/* 로딩 자리표시자 */
.skeleton {
  pointer-events: none;
}

.skeleton .thumb {
  background: var(--gray-100);
}

.sk-line {
  height: 12px;
  margin: var(--sp-4) var(--sp-4) 0;
  border-radius: 4px;
  background: var(--gray-100);
}

.sk-line.short {
  width: 55%;
  margin-bottom: var(--sp-5);
}

.skeleton {
  animation: pulse 1.4s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.55;
  }
}
</style>
