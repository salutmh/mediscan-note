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
import { bodyPartLabel, diseaseLabel, gradeBadge } from '../labels'
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
        안녕하세요, <span class="hi">{{ authState.user?.nickname ?? '학습자' }}</span> 님
      </h1>
      <p class="muted">전문가가 검수한 기준 마스크와 비교하며 훈련합니다.</p>
    </header>

    <p v-if="loading" class="skeleton-block" aria-live="polite">학습 현황을 불러오는 중…</p>
    <p v-else-if="error" class="error">{{ error }}</p>

    <template v-else-if="data">
      <!-- 1. 다음에 할 일 — 화면에서 가장 크다 -->
      <article v-if="data.next_up" class="next-card" :data-reason="data.next_up.reason">
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
        <div class="next-thumb">
          <img :src="data.next_up.thumbnail_url" alt="" />
        </div>
      </article>

      <!-- 2. 바로가기 -->
      <nav class="shortcut-row" aria-label="바로가기">
        <RouterLink class="card shortcut" to="/cases">
          <span class="chip" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5z" />
              <path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H13v16h5.5a1.5 1.5 0 0 0 1.5-1.5z" />
            </svg>
          </span>
          <span class="shortcut-text">
            <strong>케이스 학습</strong>
            <small>전체 케이스를 보고 판독을 연습합니다.</small>
          </span>
          <span class="shortcut-go" aria-hidden="true">›</span>
        </RouterLink>

        <RouterLink class="card shortcut" to="/wrong-notes">
          <span class="chip" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M8 4h8a2 2 0 0 1 2 2v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V6a2 2 0 0 1 2-2z" />
              <path d="M9 3h6v3H9z" />
              <path d="M9.5 13.5l5 0" />
            </svg>
          </span>
          <span class="shortcut-text">
            <strong>복습노트</strong>
            <small>기준과 달랐던 케이스를 다시 풉니다.</small>
          </span>
          <span class="shortcut-go" aria-hidden="true">›</span>
        </RouterLink>

        <RouterLink class="card shortcut" to="/progress">
          <span class="chip" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M5 19V11" />
              <path d="M12 19V5" />
              <path d="M19 19v-6" />
            </svg>
          </span>
          <span class="shortcut-text">
            <strong>진행현황</strong>
            <small>케이스별 학습 이력을 확인합니다.</small>
          </span>
          <span class="shortcut-go" aria-hidden="true">›</span>
        </RouterLink>
      </nav>

      <!-- 3. 진행 상황 -->
      <div class="metric-row">
        <article class="card metric">
          <p class="metric-label">
            <span class="chip sm" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                <path d="M5 19V11" /><path d="M12 19V5" /><path d="M19 19v-6" />
              </svg>
            </span>
            학습완료
          </p>
          <p class="metric-big">
            <span class="tnum">{{ totals.matched }}</span
            ><span class="metric-of">/ {{ totals.total_cases }}</span>
          </p>
          <ScoreBar :value="completionRate" tone="match" />
          <p class="metric-sub">전체의 {{ completionRate }}%</p>
        </article>

        <article class="card metric">
          <p class="metric-label">
            <span class="chip sm" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                <path d="M8 4h8a2 2 0 0 1 2 2v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V6a2 2 0 0 1 2-2z" />
                <path d="M9 3h6v3H9z" />
              </svg>
            </span>
            복습 필요
          </p>
          <p class="metric-big" :class="{ warn: totals.needs_review > 0 }">
            <span class="tnum">{{ totals.needs_review }}</span>
          </p>
          <RouterLink v-if="totals.needs_review" class="metric-link" to="/wrong-notes">
            복습노트 열기 →
          </RouterLink>
          <p v-else class="metric-sub">복습할 케이스가 없습니다</p>
        </article>

        <article class="card metric">
          <p class="metric-label">
            <span class="chip sm" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                <circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3" />
              </svg>
            </span>
            최고 일치도
          </p>
          <p v-if="data.best_dice != null" class="metric-big">
            <span class="tnum">{{ percent(data.best_dice) }}</span
            ><span class="metric-of">%</span>
          </p>
          <!-- **0 으로 채우지 않는다.** 0점과 미시도는 다른 상태다 -->
          <p v-else class="metric-empty">아직 기록 없음</p>
          <p class="metric-sub">한 케이스에서 낸 최고 기록</p>
        </article>

        <article class="card metric">
          <p class="metric-label">
            <span class="chip sm" aria-hidden="true">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                <path d="M12 7v5l3 2" /><circle cx="12" cy="12" r="8" />
              </svg>
            </span>
            총 시도
          </p>
          <p class="metric-big"><span class="tnum">{{ totals.total_attempts }}</span></p>
          <p class="metric-sub">케이스 {{ totals.attempted }}개에 걸쳐</p>
        </article>
      </div>

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

      <!-- 4. 최근 학습 활동 — 시안 05 의 표.
           반쪽 카드에 밀어 넣으면 판정·일치도·시각이 서로 겹쳐 읽힌다.
           **모드·소견 칸은 두지 않는다** — 우리에게 없는 값이라 빈 칸만 남는다. -->
      <article class="card activity-card">
        <header class="card-head">
          <h3 class="card-title">최근 학습 활동</h3>
          <RouterLink v-if="data.recent_activity.length" class="card-more" to="/progress">
            전체 학습 기록 보기 ›
          </RouterLink>
        </header>

        <table v-if="data.recent_activity.length" class="activity-table">
          <thead>
            <tr>
              <th scope="col" class="th-thumb"><span class="sr-only">영상</span></th>
              <th scope="col">학습 일시</th>
              <th scope="col">케이스</th>
              <th scope="col" class="num">일치도</th>
              <th scope="col">결과</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, i) in data.recent_activity" :key="i">
              <td class="th-thumb">
                <span class="row-thumb">
                  <img v-if="item.thumbnail_url" :src="item.thumbnail_url" alt="" />
                </span>
              </td>
              <td class="when">{{ whenLabel(item.submitted_at) }}</td>
              <td>
                <RouterLink class="activity-case" :to="`/cases/${item.case_id}`">
                  {{ item.case_id }}
                </RouterLink>
              </td>
              <td class="num tnum">
                <template v-if="item.dice != null">{{ percent(item.dice) }}%</template>
                <span v-else class="muted">—</span>
              </td>
              <td>
                <span class="badge" :class="item.grade">{{ gradeBadge(item.grade) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty-note">아직 제출한 판독이 없습니다.</p>
      </article>

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

/* --- 다음에 할 일 -------------------------------------------------------
   시안(04 메인 화면)의 hero: 흰 카드 위에 네이비 제목 + teal 버튼, 오른쪽에 그림.
   시안은 일러스트를 두지만 우리는 **실제 케이스 영상**을 둔다 — 학습자가 무엇을
   풀게 되는지 미리 보는 편이 장식보다 낫다. */
.next-card {
  display: grid;
  grid-template-columns: 1fr 240px;
  gap: var(--sp-8);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  padding: var(--sp-8);
  align-items: center;
  box-shadow: var(--shadow-sm);
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
  margin: 0 0 var(--sp-2);
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: var(--brand-600);
}
.next-body h2 {
  margin: 0;
  font-size: 32px;
  letter-spacing: -0.02em;
  color: var(--navy-700);
}
.next-meta {
  margin: var(--sp-1) 0 0;
  color: var(--ink-secondary);
  font-size: 14px;
}
.next-reason {
  margin: var(--sp-3) 0 var(--sp-6);
  font-size: 14.5px;
  color: var(--ink-secondary);
}
.btn.lg {
  padding: 12px 22px;
  font-size: 15px;
}

/* --- 바로가기 (시안 04 의 3카드) ---------------------------------------- */
.shortcut-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--sp-4);
}
.shortcut {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  text-decoration: none;
  color: inherit;
  transition: border-color var(--transition), box-shadow var(--transition);
}
.shortcut:hover {
  border-color: var(--brand-300);
  box-shadow: var(--shadow-md);
}
.shortcut-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.shortcut-text strong {
  color: var(--navy-700);
  font-size: 15px;
}
.shortcut-text small {
  color: var(--ink-muted);
  font-size: 12.5px;
  line-height: 1.5;
}
.shortcut-go {
  margin-left: auto;
  color: var(--gray-400);
  font-size: 20px;
  line-height: 1;
}
.shortcut:hover .shortcut-go {
  color: var(--brand-500);
}

/* 시안이 반복해서 쓰는 둥근 아이콘 칩 */
.chip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  width: 44px;
  height: 44px;
  border-radius: var(--r-full);
  background: var(--brand-50);
  color: var(--brand-600);
}
.chip svg {
  width: 22px;
  height: 22px;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.chip.sm {
  width: 26px;
  height: 26px;
}
.chip.sm svg {
  width: 15px;
  height: 15px;
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
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-muted);
}
.metric-big {
  margin: 0;
  font-size: 34px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--navy-700);
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

/* --- 최근 학습 활동 표 (시안 05) --- */
.activity-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
}
.activity-table th {
  padding: 0 var(--sp-3) var(--sp-2);
  text-align: left;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-muted);
  border-bottom: 1px solid var(--line);
}
.activity-table td {
  padding: 10px var(--sp-3);
  border-bottom: 1px solid var(--line);
  vertical-align: middle;
}
.activity-table tr:last-child td {
  border-bottom: 0;
}
.activity-table .num {
  text-align: right;
}
.activity-table .when {
  color: var(--ink-muted);
  font-size: 12.5px;
  white-space: nowrap;
}
.th-thumb {
  width: 52px;
}
.row-thumb {
  display: block;
  width: 40px;
  height: 40px;
  border-radius: var(--r-sm);
  overflow: hidden;
  background: var(--viewer-bg);
}
.row-thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
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

.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-3);
}
.card-more {
  color: var(--brand-600);
  font-size: 12.5px;
  font-weight: 600;
  text-decoration: none;
  white-space: nowrap;
}
.card-more:hover {
  text-decoration: underline;
}

@media (max-width: 1080px) {
  .metric-row {
    grid-template-columns: repeat(2, 1fr);
  }
  .shortcut-row {
    grid-template-columns: 1fr;
  }
  .two-col {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .next-card {
    /* 좁은 화면에서는 영상이 먼저 오고 글이 아래로. 그림 칸이 눌려 찌그러지지 않게 한다 */
    grid-template-columns: 1fr;
  }
  .next-thumb {
    order: -1;
    max-width: 200px;
  }
}
</style>
