<script setup>
/**
 * 화면 1 — 케이스 목록 (api-spec.md 2-1 / 4절 화면 1)
 * 부위 필터 탭 -> GET /api/cases?body_part=... , 카드에 썸네일 + solved 뱃지.
 */
import { onMounted, ref } from 'vue'
import { listCases } from '../api/endpoints'
import { bodyPartLabel, diseaseLabel } from '../labels'

// api-spec.md 0절의 부위 코드
const BODY_PARTS = [
  { code: '', label: '전체' },
  { code: 'brain_mri', label: '뇌 MRI' },
  { code: 'brain_ct', label: '뇌 CT' },
  { code: 'chest_xray', label: '흉부 X-ray' },
  { code: 'abdomen_ct', label: '복부 CT' },
  { code: 'knee_mri', label: '무릎 MRI' },
]

const selected = ref('')
const cases = ref([])
const loading = ref(false)
const errorMessage = ref('')

async function load() {
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await listCases(selected.value || undefined)
    cases.value = data.cases ?? []
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
function onThumbError(event) {
  event.target.style.visibility = 'hidden'
}
</script>

<template>
  <header class="head">
    <div>
      <h1>케이스 목록</h1>
      <p class="lead">판독할 케이스를 선택하세요.</p>
    </div>
  </header>

  <div class="segmented filters">
    <button
      v-for="bp in BODY_PARTS"
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

  <div v-else-if="!cases.length && !errorMessage" class="card empty">
    <p>해당 부위의 케이스가 없습니다.</p>
    <p class="muted">지금은 뇌 MRI(전정신경초종) 케이스만 등록되어 있습니다.</p>
  </div>

  <ul v-else class="grid">
    <li v-for="c in cases" :key="c.case_id">
      <RouterLink :to="{ name: 'reading', params: { caseId: c.case_id } }" class="card case-card">
        <div class="thumb">
          <img :src="c.thumbnail_url" :alt="`${c.case_id} 썸네일`" @error="onThumbError" />
          <span class="badges">
            <span v-if="c.has_matched" class="badge float match">학습완료</span>
            <span v-if="c.needs_review" class="badge float mismatch">복습필요</span>
            <span v-if="!c.has_matched && !c.needs_review" class="badge float">미시도</span>
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
        </div>
        <span class="go">판독하기 →</span>
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
