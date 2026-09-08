<script setup>
/**
 * 화면 6 — 복습노트 (api-spec.md 2-4 / 2-5, 4절 화면 6)
 * 화면 라벨은 "복습노트"지만 엔드포인트·라우트 이름은 API 계약(/api/wrong-notes)을 그대로 따른다.
 * grade 가 partial_match/mismatch 인 케이스 목록. 클릭하면 재도전 화면(판독 훈련 재사용)으로 이동하고,
 * 거기서 제출하면 POST /api/wrong-notes/{case_id}/retry 로 나간다.
 */
import { computed, onMounted, ref } from 'vue'
import { listWrongNotes } from '../api/endpoints'
import { bodyPartLabel } from '../labels'

const items = ref([])
const loading = ref(true)
const errorMessage = ref('')
const filter = ref('all') // 'all' | 'partial_match' | 'mismatch'

const GRADE_LABEL = { partial_match: '부분 일치', mismatch: '불일치' }

const visible = computed(() =>
  filter.value === 'all' ? items.value : items.value.filter((i) => i.grade === filter.value),
)
const counts = computed(() => ({
  all: items.value.length,
  partial_match: items.value.filter((i) => i.grade === 'partial_match').length,
  mismatch: items.value.filter((i) => i.grade === 'mismatch').length,
}))

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
    <p class="lead">내가 표시한 ROI가 기준 마스크와 완전히 일치하지 않았던 케이스입니다.</p>
  </header>

  <div class="segmented filters">
    <button :class="{ active: filter === 'all' }" @click="filter = 'all'">
      전체 <span class="cnt">{{ counts.all }}</span>
    </button>
    <button :class="{ active: filter === 'partial_match' }" @click="filter = 'partial_match'">
      부분 일치 <span class="cnt">{{ counts.partial_match }}</span>
    </button>
    <button :class="{ active: filter === 'mismatch' }" @click="filter = 'mismatch'">
      불일치 <span class="cnt">{{ counts.mismatch }}</span>
    </button>
  </div>

  <p v-if="errorMessage" class="error">{{ errorMessage }}</p>
  <p v-if="loading" class="muted loading">불러오는 중...</p>

  <div v-else-if="!visible.length && !errorMessage" class="card empty">
    <p>{{ items.length ? '해당 조건에 맞는 기록이 없습니다.' : '아직 복습할 기록이 없습니다.' }}</p>
    <p class="muted">케이스를 풀고 나면 일치하지 않은 판독이 여기에 모입니다.</p>
    <RouterLink to="/cases" class="btn primary go">케이스 목록으로</RouterLink>
  </div>

  <ul v-else class="list">
    <li v-for="item in visible" :key="item.case_id" class="card row">
      <span class="rail" :class="item.grade" aria-hidden="true"></span>
      <div class="row-info">
        <div class="line">
          <strong class="case-id">{{ item.case_id }}</strong>
          <span class="badge" :class="item.grade">{{ GRADE_LABEL[item.grade] ?? item.grade }}</span>
        </div>
        <p class="muted">
          {{ bodyPartLabel(item.body_part) }}
          <span class="dot">·</span>
          {{ formatDate(item.attempted_at) }} 시도
        </p>
      </div>
      <RouterLink class="btn primary" :to="{ name: 'retry', params: { caseId: item.case_id } }">
        재도전
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

.list {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.row {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  padding: var(--sp-4) var(--sp-5);
  overflow: hidden;
  transition: border-color var(--transition), box-shadow var(--transition);
}

.row:hover {
  border-color: var(--line-strong);
  box-shadow: var(--shadow-md);
}

/* 왼쪽 상태 색 띠 — 색만으로 뜻을 전하지 않게 뱃지 라벨과 함께 쓴다 */
.rail {
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
}

.rail.partial_match {
  background: var(--mark-partial);
}

.rail.mismatch {
  background: var(--mark-mismatch);
}

.row-info {
  flex: 1;
  min-width: 0;
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
