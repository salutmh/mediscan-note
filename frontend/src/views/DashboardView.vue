<script setup>
/**
 * 학습 대시보드 (시안 05) — **독립 화면.**
 *
 * 처음에는 이 내용을 홈에 합쳐 뒀는데, 시안에서는 04(메인)와 05(대시보드)가
 * 서로 다른 화면이다. 합쳐 두면 홈이 길어지기만 하고 "지금 뭘 할까"(04)와
 * "내가 어디까지 왔나"(05)가 섞인다.
 *
 * **여기 나오는 숫자는 전부 사용자 자신의 기록이다.**
 * 의료적 난이도나 소견을 만들지 않는다. 값이 없으면 0 으로 채우지 않는다 —
 * 0점과 미시도는 다른 상태다.
 *
 * 시안의 "정답률"은 우리 문구로 **기준과 일치한 비율**이다 (정답/오답이라고 쓰지 않는다).
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { getDashboard } from '../api/endpoints'
import { gradeBadge } from '../labels'

const data = ref(null)
const loading = ref(true)
const error = ref('')

/** 기간 필터 (시안 05 의 날짜 범위). 최근 활동에만 걸린다. */
const RANGES = [
  { days: 7, label: '최근 7일' },
  { days: 30, label: '최근 30일' },
  { days: 0, label: '전체 기간' },
]
const rangeDays = ref(0)

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

function percent(value) {
  return value == null ? null : Math.round(value * 100)
}

/** 진도 = 학습완료 / 전체 케이스 */
const progressRate = computed(() => {
  if (!totals.value?.total_cases) return 0
  return Math.round((totals.value.matched / totals.value.total_cases) * 100)
})

/**
 * 기준과 일치한 비율 = 학습완료 / 시도한 케이스.
 * **전체 케이스가 아니라 시도한 케이스가 분모다** — 아직 풀지 않은 것을 틀린 것으로
 * 세면 시작도 안 한 사람의 숫자가 0% 로 찍힌다.
 */
const matchRate = computed(() => {
  const attempted = totals.value?.attempted ?? 0
  if (!attempted) return null
  return Math.round((totals.value.matched / attempted) * 100)
})

/** 평균 일치도 — 케이스별 최고 기록의 평균이 아니라 **지금 가진 최고 기록**만 쓴다 */
const bestRate = computed(() => percent(data.value?.best_dice))

const recent = computed(() => {
  const items = data.value?.recent_activity ?? []
  if (!rangeDays.value) return items
  const cutoff = Date.now() - rangeDays.value * 86400000
  return items.filter((i) => new Date(i.submitted_at).getTime() >= cutoff)
})

function whenLabel(iso) {
  if (!iso) return ''
  const then = new Date(iso)
  return `${then.toLocaleDateString('ko-KR')} ${then.toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
  })}`
}
</script>

<template>
  <section class="dash">
    <header class="head">
      <div>
        <h1>학습 대시보드</h1>
        <p class="lead">나의 학습 현황을 확인하고, 부족한 부분을 보완해보세요.</p>
      </div>

      <!-- 시안 05 의 날짜 범위 자리. 최근 활동에만 걸린다 -->
      <div class="segmented range">
        <button
          v-for="r in RANGES"
          :key="r.days"
          :class="{ active: rangeDays === r.days }"
          @click="rangeDays = r.days"
        >
          {{ r.label }}
        </button>
      </div>
    </header>

    <p v-if="loading" class="skeleton-block" aria-live="polite">학습 현황을 불러오는 중…</p>
    <p v-else-if="error" class="error">{{ error }}</p>

    <template v-else-if="data">
      <!-- KPI 3장 (시안 05) -->
      <div class="kpi-row">
        <article class="card kpi">
          <span class="chip" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M5 19V11" /><path d="M12 19V5" /><path d="M19 19v-6" />
            </svg>
          </span>
          <p class="kpi-label">진도</p>
          <p class="kpi-value">
            <span class="tnum">{{ progressRate }}</span><small>%</small>
          </p>
          <div class="kpi-bar"><i :style="{ width: progressRate + '%' }"></i></div>
          <p class="kpi-sub">
            총 {{ totals.matched }} / {{ totals.total_cases }} 케이스 학습완료
          </p>
        </article>

        <article class="card kpi">
          <span class="chip" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3" />
            </svg>
          </span>
          <p class="kpi-label">기준과 일치한 비율</p>
          <!-- **0 으로 채우지 않는다.** 아직 한 번도 안 풀었으면 비율이 없다 -->
          <p v-if="matchRate != null" class="kpi-value">
            <span class="tnum">{{ matchRate }}</span><small>%</small>
          </p>
          <p v-else class="kpi-value empty">아직 기록 없음</p>
          <div class="kpi-bar"><i :style="{ width: (matchRate ?? 0) + '%' }"></i></div>
          <p class="kpi-sub">
            시도한 {{ totals.attempted }}개 중 {{ totals.matched }}개가 기준과 일치
          </p>
        </article>

        <article class="card kpi">
          <span class="chip" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M4 9V5h4M20 9V5h-4M4 15v4h4M20 15v4h-4" />
            </svg>
          </span>
          <p class="kpi-label">최고 일치도</p>
          <p v-if="bestRate != null" class="kpi-value">
            <span class="tnum">{{ bestRate }}</span><small>%</small>
          </p>
          <p v-else class="kpi-value empty">아직 기록 없음</p>
          <div class="kpi-bar"><i :style="{ width: (bestRate ?? 0) + '%' }"></i></div>
          <p class="kpi-sub">한 케이스에서 낸 최고 기록</p>
        </article>
      </div>

      <!-- 최근 학습 활동 (시안 05 의 표) -->
      <article class="card activity-card" :class="{ quiet: !recent.length }">
        <header class="card-head">
          <h2 class="card-title">최근 학습 활동</h2>
          <RouterLink class="card-more" to="/progress">전체 학습 기록 보기 ›</RouterLink>
        </header>

        <table v-if="recent.length" class="activity-table">
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
            <tr v-for="(item, i) in recent" :key="i">
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
              <td><span class="badge" :class="item.grade">{{ gradeBadge(item.grade) }}</span></td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty-note">
          {{ data.recent_activity.length ? '이 기간에는 학습 기록이 없습니다.' : '아직 제출한 판독이 없습니다.' }}
        </p>
      </article>

      <p class="muted foot">
        여기 숫자는 모두 <strong>내가 표시한 영역과 기준 마스크의 일치도</strong>입니다.
        케이스의 의학적 난이도를 뜻하지 않습니다.
      </p>
    </template>
  </section>
</template>

<style scoped>
.dash {
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
}

.head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--sp-4);
  flex-wrap: wrap;
}
.head h1 {
  margin: 0 0 4px;
  font-size: 28px;
  color: var(--navy-700);
}

.range button {
  min-height: 34px;
  font-size: 12.5px;
}

/* --- KPI 카드 (시안 05) --- */
.kpi-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--sp-4);
}
.kpi {
  display: grid;
  grid-template-columns: 46px minmax(0, 1fr);
  grid-template-areas:
    'chip label'
    'chip value'
    'bar  bar'
    'sub  sub';
  column-gap: var(--sp-4);
  row-gap: 2px;
  align-items: center;
  padding: var(--sp-5);
}
.kpi > .chip {
  grid-area: chip;
  width: 46px;
  height: 46px;
}
.kpi-label {
  grid-area: label;
  margin: 0;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--ink-muted);
}
.kpi-value {
  grid-area: value;
  margin: 0;
  font-size: 32px;
  font-weight: 800;
  line-height: 1.05;
  letter-spacing: -0.03em;
  color: var(--navy-700);
}
.kpi-value small {
  margin-left: 2px;
  font-size: 17px;
  font-weight: 700;
  color: var(--brand-600);
}
.kpi-value.empty {
  font-size: 16px;
  font-weight: 600;
  color: var(--ink-muted);
}
.kpi-bar {
  grid-area: bar;
  height: 8px;
  margin-top: var(--sp-3);
  border-radius: var(--r-full);
  background: var(--gray-100);
  overflow: hidden;
}
.kpi-bar i {
  display: block;
  height: 100%;
  border-radius: var(--r-full);
  background: var(--brand-500);
}
.kpi-sub {
  grid-area: sub;
  margin: var(--sp-2) 0 0;
  font-size: 12px;
  color: var(--ink-muted);
}

/* --- 최근 학습 활동 표 --- */
.card-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--sp-3);
  margin-bottom: var(--sp-3);
}
.card-more {
  /* 링크 글자만 두면 20px 이라 누르기 어렵다 — 면적만 넓힌다 */
  display: inline-flex;
  align-items: center;
  min-height: 44px;
  padding: 0 var(--sp-2);
  margin-right: calc(var(--sp-2) * -1);
  color: var(--brand-600);
  font-size: 12.5px;
  font-weight: 600;
  text-decoration: none;
  white-space: nowrap;
}
.card-more:hover {
  text-decoration: underline;
}

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
.activity-case {
  font-weight: 700;
  color: var(--navy-700);
  text-decoration: none;
}
.activity-case:hover {
  color: var(--brand-600);
  text-decoration: underline;
}

/* .empty-note 는 style.css 의 공통 규칙을 쓴다 (여기서 32px 위아래 여백을 주던 지역 규칙을
   걷어냈다 — 홈과 대시보드의 빈 상태가 서로 달라 보일 이유가 없다) */

.foot {
  margin: 0;
  font-size: 12.5px;
}

.skeleton-block {
  padding: var(--sp-10);
  text-align: center;
  color: var(--ink-muted);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
}

@media (max-width: 900px) {
  .kpi-row {
    grid-template-columns: 1fr;
  }
}
</style>
