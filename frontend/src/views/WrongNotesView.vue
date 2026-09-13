<script setup>
/**
 * 화면 6 — 복습노트 (api-spec.md 2-4 / 2-5, 4절 화면 6)
 * 화면 라벨은 "복습노트"지만 엔드포인트·라우트 이름은 API 계약(/api/wrong-notes)을 그대로 따른다.
 * grade 가 partial_match/mismatch 인 케이스 목록. 클릭하면 재도전 화면(판독 훈련 재사용)으로 이동하고,
 * 거기서 제출하면 POST /api/wrong-notes/{case_id}/retry 로 나간다.
 */
import { computed, onMounted, ref } from 'vue'
import { listWrongNotes } from '../api/endpoints'
import { bodyPartLabel, gradeBadge, gradeLabel } from '../labels'

const items = ref([])
const loading = ref(true)
const errorMessage = ref('')
const filter = ref('all') // 'all' | 'partial_match' | 'mismatch'


const visible = computed(() =>
  filter.value === 'all' ? items.value : items.value.filter((i) => i.grade === filter.value),
)
const counts = computed(() => ({
  all: items.value.length,
  partial_match: items.value.filter((i) => i.grade === 'partial_match').length,
  mismatch: items.value.filter((i) => i.grade === 'mismatch').length,
}))

function percent(value) {
  return value == null ? null : Math.round(value * 100)
}

/**
 * 최고 기록은 **최근 기록보다 나을 때만** 보여준다.
 * 둘이 같으면 같은 숫자가 두 번 나와 잡음이고,
 * 최근이 더 좋으면 "최고"는 지금 그 값이라 따로 말할 이유가 없다.
 */
function showsBest(item) {
  return item.best_dice != null && item.latest_dice != null && item.best_dice > item.latest_dice
}

function formatDate(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('ko-KR', { dateStyle: 'medium', timeStyle: 'short' })
}

onMounted(async () => {
  try {
    const data = await listWrongNotes()
    items.value = data.items ?? []
  } catch (e) {
    errorMessage.value = e.message
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <header class="head">
    <h1>복습노트</h1>
    <p class="lead">
      기준 마스크와 완전히 일치하지 않았던 케이스입니다. 다시 풀어 얼마나 가까워지는지 확인하세요.
    </p>
  </header>

  <div class="segmented filters">
    <button :class="{ active: filter === 'all' }" @click="filter = 'all'">
      전체 <span class="cnt">{{ counts.all }}</span>
    </button>
    <button :class="{ active: filter === 'partial_match' }" @click="filter = 'partial_match'">
      {{ gradeLabel('partial_match') }} <span class="cnt">{{ counts.partial_match }}</span>
    </button>
    <button :class="{ active: filter === 'mismatch' }" @click="filter = 'mismatch'">
      {{ gradeLabel('mismatch') }} <span class="cnt">{{ counts.mismatch }}</span>
    </button>
  </div>

  <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
  <p v-if="loading" class="muted loading">불러오는 중...</p>

  <div v-else-if="!visible.length && !errorMessage" class="card empty">
    <p>{{ items.length ? '해당 조건에 맞는 기록이 없습니다.' : '아직 복습할 기록이 없습니다.' }}</p>
    <p class="muted">케이스를 풀고 나면 일치하지 않은 판독이 여기에 모입니다.</p>
    <RouterLink to="/cases" class="btn primary go">케이스 목록으로</RouterLink>
  </div>

  <!-- 시안 09 의 카드 그리드. 한 줄짜리 목록보다 **영상이 먼저 보인다** —
       "어떤 케이스였는지"는 ID 보다 그림으로 떠오른다. -->
  <ul v-else class="grid">
    <li v-for="item in visible" :key="item.case_id" class="card note-card">
      <div class="thumb">
        <img v-if="item.thumbnail_url" :src="item.thumbnail_url" :alt="`${item.case_id} 썸네일`" />
        <span class="badge float" :class="item.grade">{{ gradeBadge(item.grade) }}</span>
      </div>

      <div class="note-body">
        <strong class="case-id">{{ item.case_id }}</strong>
        <p class="muted note-meta">
          {{ bodyPartLabel(item.body_part) }}
          <span class="dot">·</span>
          {{ formatDate(item.attempted_at) }}
          <template v-if="item.attempts > 1">
            <span class="dot">·</span> {{ item.attempts }}회 시도
          </template>
        </p>

        <!-- **재도전이 이 서비스의 핵심 학습 루프인데** 그 경과가 어디에도 없었다.
             "틀린 것 목록"이 아니라 "얼마나 가까워졌는지"를 보여준다. -->
        <div v-if="item.latest_dice != null" class="scores">
          <div class="score">
            <span class="score-label">최근</span>
            <span class="tnum score-value">{{ percent(item.latest_dice) }}%</span>
          </div>
          <div v-if="showsBest(item)" class="score best">
            <span class="score-label">최고</span>
            <span class="tnum score-value">{{ percent(item.best_dice) }}%</span>
          </div>
        </div>
        <p v-else class="muted note-meta">아직 점수 기록이 없습니다</p>
      </div>

      <!-- **먼저 보고 그다음 다시 푼다.** 바로 재도전으로 보내면 무엇을 틀렸는지
           못 본 채로 다시 칠하게 된다 (해설은 제출 직후에만 보였다). -->
      <RouterLink
        class="btn primary wide"
        :to="{ name: 'wrong-note-detail', params: { caseId: item.case_id } }"
      >
        무엇을 놓쳤는지 보기
      </RouterLink>
    </li>
  </ul>
</template>

<style scoped>
.head {
  margin-bottom: var(--sp-5);
}

.head h1 {
  margin-bottom: 4px;
}

.filters {
  margin-bottom: var(--sp-5);
}

.cnt {
  font-variant-numeric: tabular-nums;
  opacity: 0.65;
  margin-left: 2px;
}

.loading {
  padding: var(--sp-8) 0;
}

/* 시안 09 의 카드 그리드 */
.grid {
  list-style: none;
  padding: 0;
  margin: 0;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
  gap: var(--sp-4);
}

.note-card {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: 0 0 var(--sp-4);
  overflow: hidden;
  transition: border-color var(--transition), box-shadow var(--transition);
}
.note-card:hover {
  border-color: var(--brand-300);
  box-shadow: var(--shadow-md);
}

.thumb {
  position: relative;
  aspect-ratio: 1;
  background: var(--viewer-bg);
}
.thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
}

/* 상태 뱃지는 썸네일 위에. **색만으로 뜻을 전하지 않으므로** 글자를 함께 얹는다. */
.badge.float {
  position: absolute;
  top: 10px;
  right: 10px;
}

.note-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 0 var(--sp-4);
  min-width: 0;
}
.note-meta {
  margin: 0;
  font-size: 12.5px;
}

/* 최근 / 최고를 나란히 — "얼마나 가까워졌는지"가 이 화면의 요점이다 */
.scores {
  display: flex;
  gap: var(--sp-5);
  margin-top: var(--sp-2);
}
.score {
  display: flex;
  flex-direction: column;
  gap: 1px;
}
.score-label {
  font-size: 11.5px;
  color: var(--ink-muted);
}
.score-value {
  font-size: 18px;
  font-weight: 700;
  color: var(--navy-700);
}
.score.best .score-value {
  color: var(--match-ink);
}

.note-card .btn.primary {
  margin: 0 var(--sp-4);
}


.line {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.case-id {
  font-size: 14.5px;
  letter-spacing: -0.02em;
}

.row-info .muted {
  margin-top: 2px;
}

.dot {
  color: var(--gray-300);
  margin: 0 2px;
}

.btn.primary {
  text-decoration: none;
  flex: 0 0 auto;
}

.empty {
  text-align: center;
  padding: var(--sp-10) var(--sp-5);
}

.empty p:first-child {
  font-weight: 600;
  margin-bottom: 4px;
}

.empty .go {
  margin-top: var(--sp-4);
}

@media (max-width: 560px) {
  .row {
    flex-wrap: wrap;
  }

  .btn.primary {
    width: 100%;
  }
}
</style>
