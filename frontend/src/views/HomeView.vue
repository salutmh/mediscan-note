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
    <p v-if="loading" class="skeleton-block" aria-live="polite">학습 현황을 불러오는 중…</p>
    <p v-else-if="error" class="error">{{ error }}</p>

    <template v-else-if="data">
      <!-- 1. hero — 시안 04. **인사말이 화면의 머리말이고**, 오른쪽은 그림이다.
           (예전에는 케이스 카드가 이 자리에 있어서 첫인상이 "목록"이었다) -->
      <article class="hero">
        <div class="hero-body">
          <h1>안녕하세요, <span class="hi">{{ authState.user?.nickname ?? '학습자' }}</span> 님</h1>
          <!-- **처음 온 사람과 이어서 하는 사람에게 다른 말을 한다.**
               시안에는 인사말만 있지만, 이 한 줄이 "지금 뭘 해야 하나"에 답한다. -->
          <p class="hero-sub">
            <strong>{{ data.has_any_activity ? '이어서 학습하기' : '여기서 시작하세요' }}</strong>
            <span class="dot">·</span>
            전문가가 검수한 기준과 비교하며 판독을 연습합니다.
          </p>

          <RouterLink
            v-if="data.next_up"
            class="hero-cta"
            :to="`/cases/${data.next_up.case_id}`"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" aria-hidden="true">
              <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5z" />
              <path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H13v16h5.5a1.5 1.5 0 0 0 1.5-1.5z" />
            </svg>
            {{ nextLabel }}
            <span class="cta-caret" aria-hidden="true">›</span>
          </RouterLink>

          <!-- **이유 없는 추천은 신뢰받지 못한다.** 시안에는 없지만 남긴다. -->
          <p v-if="data.next_up" class="hero-next">
            다음 케이스 <strong>{{ data.next_up.case_id }}</strong>
            <span class="dot">·</span> {{ nextReason }}
          </p>
        </div>

        <!-- 시안의 일러스트 자리. **실제 환자 영상을 장식으로 쓰지 않는다** —
             책·돋보기·판독지 모티프를 직접 그린다. -->
        <div class="hero-art" aria-hidden="true">
          <svg viewBox="0 0 240 170" fill="none">
            <ellipse cx="126" cy="150" rx="96" ry="12" fill="var(--brand-50)" />
            <rect x="96" y="20" width="118" height="86" rx="8" fill="#fff" stroke="var(--brand-300)" stroke-width="2" />
            <rect x="108" y="34" width="40" height="5" rx="2.5" fill="var(--brand-300)" />
            <rect x="108" y="48" width="92" height="4" rx="2" fill="var(--gray-200)" />
            <rect x="108" y="60" width="76" height="4" rx="2" fill="var(--gray-200)" />
            <rect x="108" y="72" width="86" height="4" rx="2" fill="var(--gray-200)" />
            <rect x="108" y="84" width="54" height="4" rx="2" fill="var(--gray-200)" />
            <path d="M171 26c5-6 15-2 15 6 0 7-9 13-15 18-6-5-15-11-15-18 0-8 10-12 15-6z" fill="var(--brand-400)" opacity="0.9" />
            <rect x="26" y="92" width="104" height="16" rx="5" fill="var(--brand-500)" />
            <rect x="20" y="76" width="104" height="16" rx="5" fill="var(--brand-400)" />
            <rect x="30" y="60" width="104" height="16" rx="5" fill="var(--brand-300)" />
            <circle cx="168" cy="112" r="26" fill="#fff" fill-opacity="0.6" stroke="var(--navy-700)" stroke-width="5" />
            <path d="M188 132l18 18" stroke="var(--navy-700)" stroke-width="7" stroke-linecap="round" />
            <circle cx="46" cy="34" r="5" fill="var(--brand-300)" />
            <circle cx="66" cy="20" r="3" fill="var(--brand-400)" />
            <circle cx="212" cy="128" r="4" fill="var(--brand-300)" />
          </svg>
        </div>
      </article>

      <!-- 2. 바로가기 -->
      <nav class="shortcut-row" aria-label="바로가기">
        <RouterLink class="card shortcut" to="/learn">
          <span class="chip" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5z" />
              <path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H13v16h5.5a1.5 1.5 0 0 0 1.5-1.5z" />
            </svg>
          </span>
          <span class="shortcut-text">
            <strong>학습 시작</strong>
            <small>부위와 질환을 골라 학습을 시작합니다.</small>
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

        <RouterLink class="card shortcut" to="/dashboard">
          <span class="chip" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M5 19V11" />
              <path d="M12 19V5" />
              <path d="M19 19v-6" />
            </svg>
          </span>
          <span class="shortcut-text">
            <strong>학습 기록</strong>
            <small>지금까지의 진도와 일치도를 봅니다.</small>
          </span>
          <span class="shortcut-go" aria-hidden="true">›</span>
        </RouterLink>
      </nav>

      <!-- 3. 학습 현황 띠 — 시안 04 하단.
           시안 05 의 KPI 카드와 숫자가 겹쳐서, 홈에서는 **띠 하나로 합친다.**
           자세한 지표는 진행현황 화면이 맡는다. -->
      <article class="card stat-strip">
        <div class="strip-lead">
          <span class="chip" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <rect x="4" y="5" width="16" height="16" rx="2" />
              <path d="M4 10h16M9 3v4M15 3v4" />
            </svg>
          </span>
          <span class="strip-text">
            <strong>내 학습 현황</strong>
            <small>전문가가 검수한 기준과 비교한 내 기록입니다.</small>
          </span>
        </div>

        <div class="strip-item">
          <span class="chip sm" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M4 12.5l5 5L20 7" />
            </svg>
          </span>
          <span class="strip-text">
            <small>학습완료</small>
            <strong class="strip-value">
              <span class="tnum">{{ totals.matched }}</span
              ><span class="strip-of">/ {{ totals.total_cases }}</span>
            </strong>
          </span>
        </div>

        <div class="strip-item">
          <span class="chip sm" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M8 4h8a2 2 0 0 1 2 2v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V6a2 2 0 0 1 2-2z" />
              <path d="M9 3h6v3H9z" />
            </svg>
          </span>
          <span class="strip-text">
            <small>복습 필요</small>
            <strong class="strip-value" :class="{ warn: totals.needs_review > 0 }">
              <span class="tnum">{{ totals.needs_review }}</span>
            </strong>
          </span>
        </div>

        <div class="strip-item">
          <span class="chip sm" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3" />
            </svg>
          </span>
          <span class="strip-text">
            <small>최고 일치도</small>
            <!-- **0 으로 채우지 않는다.** 0점과 미시도는 다른 상태다 -->
            <strong v-if="data.best_dice != null" class="strip-value">
              <span class="tnum">{{ percent(data.best_dice) }}</span><span class="strip-of">%</span>
            </strong>
            <strong v-else class="strip-value empty">아직 기록 없음</strong>
          </span>
        </div>

        <div class="strip-item">
          <span class="chip sm" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M12 7v5l3 2" /><circle cx="12" cy="12" r="8" />
            </svg>
          </span>
          <span class="strip-text">
            <small>총 시도</small>
            <strong class="strip-value"><span class="tnum">{{ totals.total_attempts }}</span></strong>
          </span>
        </div>
      </article>

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

/* --- hero (시안 04) — 인사말이 머리말이고 오른쪽은 그림이다 --- */
.hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: var(--sp-6);
  align-items: center;
  padding: var(--sp-10) var(--sp-8);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-sm);
}

.hero h1 {
  margin: 0;
  font-size: 34px;
  letter-spacing: -0.035em;
  color: var(--navy-700);
}
.hi {
  color: var(--brand-600);
}

.hero-sub {
  margin: var(--sp-3) 0 var(--sp-6);
  color: var(--ink-secondary);
  font-size: 14.5px;
}
.hero-sub strong {
  color: var(--brand-700);
}

/* 시안의 teal 알약 버튼 */
.hero-cta {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 13px 22px;
  border-radius: var(--r-md);
  background: var(--brand-500);
  color: #fff;
  font-size: 15px;
  font-weight: 700;
  text-decoration: none;
  transition: background var(--transition);
}
.hero-cta:hover {
  background: var(--brand-600);
  color: #fff;
}
.hero-cta svg {
  width: 19px;
  height: 19px;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.cta-caret {
  margin-left: var(--sp-4);
  font-size: 19px;
  line-height: 1;
  opacity: 0.85;
}

.hero-next {
  margin: var(--sp-4) 0 0;
  color: var(--ink-muted);
  font-size: 12.5px;
}
.hero-next strong {
  color: var(--ink-secondary);
}

.hero-art {
  justify-self: center;
}
.hero-art svg {
  width: 100%;
  max-width: 280px;
  height: auto;
  display: block;
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
/* --- 학습 현황 띠 (시안 04 하단) — 한 장짜리 카드를 얇은 구분선으로 나눈다 --- */
.stat-strip {
  display: grid;
  /* 시안은 리드 칸 + 지표 3칸이지만 우리는 보여줄 지표가 4개다.
     리드 칸(시안의 모양)은 남기고 지표 칸만 하나 늘렸다. */
  grid-template-columns: minmax(0, 1.6fr) repeat(4, minmax(0, 1fr));
  align-items: center;
  gap: 0;
  padding: var(--sp-5) 0;
}
.strip-lead,
.strip-item {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 0 var(--sp-5);
  min-width: 0;
}
.strip-item {
  border-left: 1px solid var(--line);
}
.strip-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.strip-text strong {
  color: var(--navy-700);
  font-size: 15px;
}
.strip-text small {
  color: var(--ink-muted);
  font-size: 12px;
  line-height: 1.5;
}
.strip-value {
  font-size: 24px;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--brand-700);
}
.strip-value.warn {
  color: var(--mark-partial);
}
.strip-value.empty {
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-muted);
}
.strip-of {
  margin-left: 3px;
  font-size: 14px;
  font-weight: 600;
  color: var(--ink-muted);
}

@media (max-width: 900px) {
  .stat-strip {
    grid-template-columns: 1fr 1fr;
    row-gap: var(--sp-5);
  }
  .strip-lead {
    grid-column: 1 / -1;
  }
  /* 줄이 바뀌면 왼쪽 구분선이 어색해진다 — 각 줄의 첫 칸에서는 뗀다 */
  .strip-item:nth-child(even) {
    border-left: 0;
  }
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
  .shortcut-row {
    grid-template-columns: 1fr;
  }
  .two-col {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
  .hero {
    /* 좁은 화면에서는 그림을 빼고 글과 버튼에 폭을 준다 (그림은 장식이다) */
    grid-template-columns: 1fr;
    padding: var(--sp-6);
  }
  .hero h1 {
    font-size: 26px;
  }
  .hero-art {
    display: none;
  }
}
</style>
