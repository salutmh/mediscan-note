<script setup>
/**
 * 홈 = 학습 대시보드 (화면 1의 앞단).
 *
 * **왜 만들었나**
 * 지금까지 `/` 는 케이스 목록으로 바로 넘어갔다. 앱을 열면 격자만 있고
 * "내가 어디까지 했는지" "다음에 뭘 해야 하는지"가 어디에도 없었다.
 * 그 정보는 전부 서버에 있었는데(제출 이력) 화면까지 오지 못했다.
 *
 * **여기 있는 숫자는 전부 사용자 자신의 기록이다.**
 * 의료적 난이도나 소견을 만들지 않는다. 값이 없으면 0 으로 채우지 않고
 * "아직 기록이 없습니다"로 둔다 — 0점과 미시도는 다른 상태다.
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { getDashboard } from '../api/endpoints'
import { authState } from '../stores/auth'
import { bodyPartLabel, diseaseLabel } from '../labels'
import ScoreBar from '../components/ScoreBar.vue'

const data = ref(null)
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    data.value = await getDashboard()
  } catch (e) {
    error.value = e.message || '학습 현황을 불러오지 못했습니다.'
  } finally {
    loading.value = false
  }
})

const totals = computed(() => data.value?.totals ?? null)

const completionRate = computed(() => {
  if (!totals.value?.total_cases) return 0
  return Math.round((totals.value.matched / totals.value.total_cases) * 100)
})

// 추천 이유를 사용자 문장으로. **이유 없는 추천은 신뢰받지 못한다.**
const NEXT_REASON = {
  needs_review: '지난번 기준과 달라서 복습이 필요한 케이스입니다',
  not_started: '아직 풀지 않은 케이스입니다',
  all_matched: '모든 케이스를 한 번씩 맞혔습니다. 다시 풀어볼 수 있습니다',
}
const nextReason = computed(() => NEXT_REASON[data.value?.next_up?.reason] ?? '')
const nextLabel = computed(() =>
  data.value?.next_up?.reason === 'needs_review' ? '복습하기' : '학습 시작',
)

const improvement = computed(() => data.value?.latest_improvement ?? null)
const improvedBy = computed(() => {
  if (!improvement.value) return null
  return Math.round(improvement.value.delta * 100)
})

const GRADE_LABEL = { match: '일치', partial_match: '부분 일치', mismatch: '불일치' }

function percent(value) {
  return value == null ? null : Math.round(value * 100)
}

function whenLabel(iso) {
  if (!iso) return ''
  const then = new Date(iso)
  const minutes = Math.floor((Date.now() - then.getTime()) / 60000)
  if (minutes < 1) return '방금'
  if (minutes < 60) return `${minutes}분 전`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}시간 전`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}일 전`
  return then.toLocaleDateString('ko-KR')
}
</script>

<template>
  <section class="home">
    <header class="greeting">
      <h1>
        <span class="hi">{{ authState.user?.nickname ?? '학습자' }}</span> 님, 오늘도 판독 연습해요
      </h1>
      <p class="muted">전문가가 검수한 기준 마스크와 비교하며 훈련합니다.</p>
    </header>

    <p v-if="loading" class="skeleton-block" aria-live="polite">학습 현황을 불러오는 중…</p>
    <p v-else-if="error" class="error">{{ error }}</p>

    <template v-else-if="data">
      <!-- 1. 다음에 할 일 — 화면에서 가장 크다 -->
      <article v-if="data.next_up" class="next-card" :data-reason="data.next_up.reason">
        <div class="next-thumb">
          <img :src="data.next_up.thumbnail_url" alt="" />
        </div>
        <div class="next-body">
          <p class="next-kicker">{{ data.has_any_activity ? '이어서 학습하기' : '여기서 시작하세요' }}</p>
          <h2>{{ data.next_up.case_id }}</h2>
          <p class="next-meta">
            {{ bodyPartLabel(data.next_up.body_part) }} · {{ diseaseLabel(data.next_up.disease) }}
          </p>
          <p class="next-reason">{{ nextReason }}</p>
          <RouterLink class="btn primary lg" :to="`/cases/${data.next_up.case_id}`">
            {{ nextLabel }} →
          </RouterLink>
        </div>
      </article>

      <!-- 2. 진행 상황 -->
      <div class="metric-row">
        <article class="card metric">
          <p class="metric-label">학습완료</p>
          <p class="metric-big">
            <span class="tnum">{{ totals.matched }}</span
            ><span class="metric-of">/ {{ totals.total_cases }}</span>
          </p>
          <ScoreBar :value="completionRate" tone="match" />
          <p class="metric-sub">전체의 {{ completionRate }}%</p>
        </article>

        <article class="card metric">
          <p class="metric-label">복습 필요</p>
          <p class="metric-big" :class="{ warn: totals.needs_review > 0 }">
            <span class="tnum">{{ totals.needs_review }}</span>
          </p>
          <RouterLink v-if="totals.needs_review" class="metric-link" to="/wrong-notes">
            복습노트 열기 →
          </RouterLink>
          <p v-else class="metric-sub">복습할 케이스가 없습니다</p>
        </article>

        <article class="card metric">
          <p class="metric-label">최고 일치도</p>
          <p v-if="data.best_dice != null" class="metric-big">
            <span class="tnum">{{ percent(data.best_dice) }}</span
            ><span class="metric-of">%</span>
          </p>
          <!-- **0 으로 채우지 않는다.** 0점과 미시도는 다른 상태다 -->
          <p v-else class="metric-empty">아직 기록 없음</p>
          <p class="metric-sub">한 케이스에서 낸 최고 기록</p>
        </article>

        <article class="card metric">
          <p class="metric-label">총 시도</p>
          <p class="metric-big"><span class="tnum">{{ totals.total_attempts }}</span></p>
          <p class="metric-sub">케이스 {{ totals.attempted }}개에 걸쳐</p>
        </article>
      </div>

      <div class="two-col">
        <!-- 3. 재도전으로 얼마나 나아졌나 -->
        <article class="card">
          <h3 class="card-title">최근 재도전</h3>
          <div v-if="improvement" class="improve">
            <p class="improve-case">{{ improvement.case_id }}</p>
            <div class="improve-compare">
              <div class="improve-step">
                <span class="improve-when">이전</span>
                <span class="tnum improve-score">{{ percent(improvement.previous_dice) }}%</span>
              </div>
              <span class="improve-arrow" aria-hidden="true">→</span>
              <div class="improve-step">
                <span class="improve-when">이번</span>
                <span class="tnum improve-score now">{{ percent(improvement.latest_dice) }}%</span>
              </div>
              <span class="improve-delta" :class="improvedBy >= 0 ? 'up' : 'down'">
                {{ improvedBy >= 0 ? '+' : '' }}{{ improvedBy }}p
              </span>
            </div>
            <p class="muted improve-note">
              같은 케이스의 마지막 두 시도를 비교한 값입니다.
            </p>
          </div>
          <p v-else class="empty-note">
            같은 케이스를 두 번 이상 풀면 여기에 변화가 나타납니다.
          </p>
        </article>

        <!-- 4. 최근 활동 -->
        <article class="card">
          <h3 class="card-title">최근 학습</h3>
          <ul v-if="data.recent_activity.length" class="activity">
            <li v-for="(item, i) in data.recent_activity" :key="i">
              <RouterLink class="activity-case" :to="`/cases/${item.case_id}`">
                {{ item.case_id }}
              </RouterLink>
              <span class="badge" :class="item.grade">{{ GRADE_LABEL[item.grade] ?? item.grade }}</span>
              <span v-if="item.dice != null" class="tnum activity-score">{{ percent(item.dice) }}%</span>
              <span class="activity-when muted">{{ whenLabel(item.submitted_at) }}</span>
            </li>
          </ul>
          <p v-else class="empty-note">아직 제출한 판독이 없습니다.</p>
        </article>
      </div>

      <RouterLink class="all-cases" to="/cases">
        전체 케이스 {{ totals.total_cases }}개 보기 →
      </RouterLink>
    </template>
  </section>
</template>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: var(--sp-6);
}

.greeting h1 {
  margin: 0 0 var(--sp-2);
}
.hi {
  color: var(--accent);
}

/* --- 다음에 할 일 ------------------------------------------------------- */
.next-card {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: var(--sp-6);
  background: linear-gradient(135deg, var(--brand-700), var(--brand-500));
  color: #fff;
  border-radius: var(--r-lg);
  padding: var(--sp-6);
  align-items: center;
}
.next-thumb {
  aspect-ratio: 1;
  border-radius: var(--r-md);
  overflow: hidden;
  background: var(--viewer-bg);
}
.next-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}
.next-kicker {
  margin: 0 0 var(--sp-1);
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  opacity: 0.85;
}
.next-body h2 {
  margin: 0;
  font-size: 30px;
  letter-spacing: -0.01em;
}
.next-meta {
  margin: var(--sp-1) 0 0;
  opacity: 0.85;
  font-size: 14px;
}
.next-reason {
  margin: var(--sp-3) 0 var(--sp-5);
  font-size: 14.5px;
  opacity: 0.95;
}
.next-card .btn.primary {
  background: #fff;
  color: var(--brand-700);
  border-color: #fff;
}
.next-card .btn.primary:hover:not(:disabled) {
  background: var(--brand-50);
  color: var(--brand-700);
}
.btn.lg {
  padding: 12px 22px;
  font-size: 15px;
}

/* --- 지표 --------------------------------------------------------------- */
.metric-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: var(--sp-4);
}
.metric {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.metric-label {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-muted);
}
.metric-big {
  margin: 0;
  font-size: 32px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--ink);
}
.metric-big.warn {
  color: var(--mark-partial);
}
.metric-of {
  font-size: 16px;
  font-weight: 500;
  color: var(--ink-muted);
  margin-left: 4px;
}
.metric-empty {
  margin: 0;
  font-size: 17px;
  font-weight: 500;
  color: var(--ink-muted);
  padding: 6px 0;
}
.metric-sub,
.metric-link {
  margin: 0;
  font-size: 12.5px;
  color: var(--ink-muted);
}
.metric-link {
  color: var(--accent);
  font-weight: 600;
  text-decoration: none;
}
.metric-link:hover {
  text-decoration: underline;
}

/* --- 아래 두 칸 --------------------------------------------------------- */
.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-4);
  align-items: start;
}

.improve-case {
  margin: 0 0 var(--sp-3);
  font-weight: 600;
}
.improve-compare {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
}
.improve-step {
  display: flex;
  flex-direction: column;
}
.improve-when {
  font-size: 12px;
  color: var(--ink-muted);
}
.improve-score {
  font-size: 26px;
  font-weight: 700;
  color: var(--ink-secondary);
}
.improve-score.now {
  color: var(--ink);
}
.improve-arrow {
  color: var(--gray-400);
  font-size: 20px;
}
.improve-delta {
  margin-left: auto;
  font-weight: 700;
  font-size: 15px;
  padding: 4px 10px;
  border-radius: var(--r-full);
}
.improve-delta.up {
  background: var(--match-bg);
  color: var(--match-ink);
}
.improve-delta.down {
  background: var(--mismatch-bg);
  color: var(--mismatch-ink);
}
.improve-note {
  margin: var(--sp-4) 0 0;
  font-size: 12.5px;
}

.activity {
  list-style: none;
  margin: 0;
  padding: 0;
}
.activity li {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 9px 0;
  border-top: 1px solid var(--line);
}
.activity li:first-child {
  border-top: 0;
}
.activity-case {
  font-weight: 600;
  color: var(--ink);
  text-decoration: none;
}
.activity-case:hover {
  color: var(--accent);
  text-decoration: underline;
}
.activity-score {
  font-variant-numeric: tabular-nums;
  color: var(--ink-secondary);
  font-size: 13.5px;
}
.activity-when {
  margin-left: auto;
  font-size: 12.5px;
}

.empty-note {
  margin: 0;
  padding: var(--sp-5) 0;
  color: var(--ink-muted);
  font-size: 14px;
  text-align: center;
}

.all-cases {
  align-self: flex-start;
  color: var(--accent);
  font-weight: 600;
  text-decoration: none;
}
.all-cases:hover {
  text-decoration: underline;
}

.skeleton-block {
  padding: var(--sp-10);
  text-align: center;
  color: var(--ink-muted);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
}

@media (max-width: 1080px) {
  .metric-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .two-col {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .next-card {
    grid-template-columns: 1fr;
  }
  .next-thumb {
    max-width: 180px;
  }
}
</style>
