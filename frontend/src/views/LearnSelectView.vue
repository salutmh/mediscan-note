<script setup>
/**
 * 학습 선택 (시안 06) — **독립 화면.**
 *
 * 부위 → 영상 종류 → 질환을 골라 학습을 시작한다.
 *
 * 여기서 지키는 것
 * --------------
 * **없는 콘텐츠를 있는 것처럼 보여주지 않는다.** 계약상 부위는 5개지만 지금 등록된
 * 케이스는 뇌 MRI 뿐이다. 그래서 카드는 시안처럼 전부 보여주되 **준비되지 않은 것은
 * 누를 수 없고 "준비 중"이라고 적는다.** 눌러서 빈 화면을 만나게 하지 않는다.
 * (예전에 부위 탭을 전부 깔았다가 빈 화면을 네 번 만나서 뺐던 적이 있다.)
 *
 * 선택지는 **실제 케이스 목록에서 만든다.** 화면에 하드코딩해 두면 케이스가 늘어도
 * 여기만 옛 상태로 남는다.
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { listCases } from '../api/endpoints'
import { bodyPartLabel, diseaseLabel } from '../labels'

const router = useRouter()

const cases = ref([])
const loading = ref(true)
const errorMessage = ref('')

const bodyPart = ref('')
const modality = ref('')
const disease = ref('')

onMounted(async () => {
  try {
    cases.value = (await listCases()).cases ?? []
  } catch (e) {
    errorMessage.value = e.message
  } finally {
    loading.value = false
  }
})

/* ------------------------------------------------------------------ 1단계 */
/** 계약에 정의된 부위 (docs/api-spec.md). 등록 여부와 무관하게 **제품의 범위**다. */
const BODY_PARTS = [
  { code: 'brain_mri', modality: 'MRI' },
  { code: 'chest_xray', modality: 'X-ray' },
  { code: 'abdomen_ct', modality: 'CT' },
  { code: 'knee_mri', modality: 'MRI' },
  { code: 'brain_ct', modality: 'CT' },
]

const PART_ICON = {
  brain_mri: ['M9 4.5a3 3 0 0 0-3 3 2.6 2.6 0 0 0-1 5 3 3 0 0 0 2.4 4.4A2.8 2.8 0 0 0 12 19V5.6A2.6 2.6 0 0 0 9 4.5z', 'M15 4.5a3 3 0 0 1 3 3 2.6 2.6 0 0 1 1 5 3 3 0 0 1-2.4 4.4A2.8 2.8 0 0 1 12 19'],
  brain_ct: ['M9 4.5a3 3 0 0 0-3 3 2.6 2.6 0 0 0-1 5 3 3 0 0 0 2.4 4.4A2.8 2.8 0 0 0 12 19V5.6A2.6 2.6 0 0 0 9 4.5z', 'M15 4.5a3 3 0 0 1 3 3 2.6 2.6 0 0 1 1 5 3 3 0 0 1-2.4 4.4A2.8 2.8 0 0 1 12 19'],
  chest_xray: ['M12 4v9', 'M8 5c0 5-1 7-3 8 0-4 .5-6 1-8z', 'M16 5c0 5 1 7 3 8 0-4-.5-6-1-8z'],
  abdomen_ct: ['M6 8c0-2 2-3.5 4.5-3.5S15 6 15 8s-1 3-1 5 1 3 1 5', 'M6 8c0 3 2 4 4 4'],
  knee_mri: ['M9 4v5a4 4 0 0 0 4 4', 'M15 20v-5a4 4 0 0 0-4-4', 'M7 12h2'],
}

const readyParts = computed(() => new Set(cases.value.map((c) => c.body_part)))

const partCards = computed(() =>
  BODY_PARTS.map((p) => ({
    ...p,
    label: bodyPartLabel(p.code),
    count: cases.value.filter((c) => c.body_part === p.code).length,
    ready: readyParts.value.has(p.code),
    paths: PART_ICON[p.code],
  })),
)

/* ------------------------------------------------------------------ 2단계 */
/** 영상 종류는 부위에 딸려 온다 (뇌 MRI = MRI). 고른 부위의 것만 활성이다. */
const MODALITIES = [
  { code: 'X-ray', desc: '일반 X-ray 영상' },
  { code: 'CT', desc: '컴퓨터 단층촬영' },
  { code: 'MRI', desc: '자기 공명 영상' },
]
const availableModality = computed(
  () => partCards.value.find((p) => p.code === bodyPart.value)?.modality ?? null,
)

/* ------------------------------------------------------------------ 3단계 */
const diseaseOptions = computed(() => {
  if (!bodyPart.value) return []
  const codes = [...new Set(cases.value.filter((c) => c.body_part === bodyPart.value).map((c) => c.disease))]
  return codes.map((code) => ({
    code,
    label: diseaseLabel(code),
    count: cases.value.filter((c) => c.body_part === bodyPart.value && c.disease === code).length,
  }))
})

/* ------------------------------------------------------------------ 진행 */
const step = computed(() => {
  if (!bodyPart.value) return 1
  if (!modality.value) return 2
  return 3
})
const canStart = computed(() => Boolean(bodyPart.value && modality.value && disease.value))

/** 고른 조건에 맞는 케이스 수 — **시작 버튼을 누르기 전에** 몇 개인지 보인다 */
const matchCount = computed(
  () =>
    cases.value.filter(
      (c) => c.body_part === bodyPart.value && (!disease.value || c.disease === disease.value),
    ).length,
)

function pickPart(card) {
  if (!card.ready) return
  bodyPart.value = bodyPart.value === card.code ? '' : card.code
  // 부위가 바뀌면 아래 단계는 다시 고른다 (이전 선택이 남으면 조합이 어긋난다)
  modality.value = ''
  disease.value = ''
}

function start() {
  if (!canStart.value) return
  router.push({ path: '/cases', query: { body_part: bodyPart.value, disease: disease.value } })
}
</script>

<template>
  <div class="learn">
    <!-- 시안 06 의 좌측 사이드바 -->
    <aside class="side">
      <RouterLink to="/" class="side-brand">
        <span class="side-mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-4.2-4.2" stroke-linecap="round" />
            <path d="M11 8v6M8 11h6" stroke-linecap="round" />
          </svg>
        </span>
        <span class="side-name">
          메디스캔노트
          <small>LEARNING</small>
        </span>
      </RouterLink>

      <nav class="side-nav">
        <RouterLink to="/learn" class="side-link current">학습하기</RouterLink>
        <RouterLink to="/progress" class="side-link">학습 기록</RouterLink>
        <RouterLink to="/wrong-notes" class="side-link">복습노트</RouterLink>
        <RouterLink to="/dashboard" class="side-link">대시보드</RouterLink>
        <RouterLink to="/account" class="side-link">설정</RouterLink>
      </nav>

      <div class="side-help">
        <span class="chip" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
            <path d="M9.5 17h5M12 3a6 6 0 0 0-3.5 10.9V16h7v-2.1A6 6 0 0 0 12 3z" />
          </svg>
        </span>
        <p><strong>어디서부터 볼까요?</strong><br />케이스 목록에서 바로 고를 수도 있습니다.</p>
        <RouterLink class="btn sm wide" to="/cases">케이스 목록</RouterLink>
      </div>
    </aside>

    <main class="main">
      <h1>학습하기</h1>

      <!-- 3단계 표시 -->
      <ol class="steps" aria-label="학습 선택 단계">
        <li :class="{ done: step > 1, current: step === 1 }"><span>1</span> 부위 선택</li>
        <li :class="{ done: step > 2, current: step === 2 }"><span>2</span> 영상 종류</li>
        <li :class="{ current: step === 3 }"><span>3</span> 질환 선택</li>
      </ol>

      <p v-if="loading" class="muted loading">불러오는 중…</p>
      <p v-else-if="errorMessage" class="error">{{ errorMessage }}</p>

      <div v-else class="card panel">
        <!-- 1. 부위 -->
        <section class="block">
          <h2>1. 부위 선택</h2>
          <ul class="pick-row">
            <li v-for="p in partCards" :key="p.code">
              <button
                class="pick"
                :class="{ active: bodyPart === p.code, pending: !p.ready }"
                :disabled="!p.ready"
                :aria-pressed="bodyPart === p.code"
                @click="pickPart(p)"
              >
                <span class="pick-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
                    <path v-for="(d, i) in p.paths" :key="i" :d="d" />
                  </svg>
                </span>
                <span class="pick-label">{{ p.label }}</span>
                <!-- **색만으로 알리지 않는다** — 준비 여부를 글자로 쓴다 -->
                <span class="pick-meta">{{ p.ready ? `${p.count}케이스` : '준비 중' }}</span>
              </button>
            </li>
          </ul>
        </section>

        <!-- 2. 영상 종류 -->
        <section class="block">
          <h2>2. 영상 종류</h2>
          <p v-if="!bodyPart" class="muted step-hint">부위를 먼저 고르면 선택할 수 있습니다.</p>
          <ul class="pick-row">
            <li v-for="m in MODALITIES" :key="m.code">
              <button
                class="pick wide-pick"
                :class="{ active: modality === m.code, pending: m.code !== availableModality }"
                :disabled="m.code !== availableModality"
                :aria-pressed="modality === m.code"
                @click="modality = modality === m.code ? '' : m.code"
              >
                <span class="pick-label">{{ m.code }}</span>
                <span class="pick-meta">
                  {{ m.code === availableModality ? m.desc : '해당 부위에 없음' }}
                </span>
              </button>
            </li>
          </ul>
        </section>

        <!-- 3. 질환 -->
        <section class="block">
          <h2>3. 질환 선택</h2>
          <p v-if="!modality" class="muted step-hint">영상 종류를 먼저 고르면 선택할 수 있습니다.</p>
          <ul v-else class="chip-row">
            <li v-for="d in diseaseOptions" :key="d.code">
              <button
                class="disease-chip"
                :class="{ active: disease === d.code }"
                :aria-pressed="disease === d.code"
                @click="disease = disease === d.code ? '' : d.code"
              >
                {{ d.label }}
                <span class="chip-mark" aria-hidden="true">{{ disease === d.code ? '✓' : '' }}</span>
              </button>
            </li>
          </ul>
        </section>

        <button class="primary lg wide start" :disabled="!canStart" @click="start">
          {{ canStart ? `학습 시작 (${matchCount}케이스)` : '학습 시작' }}
        </button>
        <p v-if="!canStart" class="muted step-hint center">
          세 단계를 모두 고르면 시작할 수 있습니다.
        </p>
      </div>
    </main>
  </div>
</template>

<style scoped>
.learn {
  display: grid;
  grid-template-columns: 236px minmax(0, 1fr);
  gap: var(--sp-6);
  align-items: start;
}

/* --- 좌측 사이드바 (시안 06) --- */
.side {
  position: sticky;
  top: 76px;
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
  padding: var(--sp-5);
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--r-lg);
}
.side-brand {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  text-decoration: none;
  color: var(--navy-700);
}
.side-mark {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  background: var(--brand-500);
  color: #fff;
}
.side-mark svg {
  width: 17px;
  height: 17px;
}
.side-name {
  display: flex;
  flex-direction: column;
  font-weight: 800;
  font-size: 14.5px;
  letter-spacing: -0.03em;
}
.side-name small {
  font-size: 9.5px;
  font-weight: 700;
  letter-spacing: 0.18em;
  color: var(--brand-600);
}

.side-nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.side-link {
  display: block;
  min-height: 38px;
  padding: 9px var(--sp-3);
  border-radius: var(--r-sm);
  color: var(--ink-secondary);
  font-size: 13.5px;
  text-decoration: none;
}
.side-link:hover {
  background: var(--gray-50);
  color: var(--ink);
}
.side-link.current {
  background: var(--brand-50);
  color: var(--brand-700);
  font-weight: 700;
}

.side-help {
  margin-top: auto;
  padding: var(--sp-4);
  border-radius: var(--r-md);
  background: var(--gray-25);
  border: 1px solid var(--line);
  text-align: center;
}
.side-help p {
  margin: var(--sp-2) 0 var(--sp-3);
  font-size: 11.5px;
  line-height: 1.6;
  color: var(--ink-muted);
}
.side-help .chip {
  width: 34px;
  height: 34px;
}
.side-help .chip svg {
  width: 18px;
  height: 18px;
  stroke-linecap: round;
  stroke-linejoin: round;
}

/* --- 본문 --- */
.main h1 {
  margin: 0 0 var(--sp-4);
  font-size: 28px;
  color: var(--navy-700);
}

.steps {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  list-style: none;
  margin: 0 0 var(--sp-4);
  padding: 0;
}
.steps li {
  display: flex;
  align-items: center;
  gap: 7px;
  flex: 1;
  font-size: 13px;
  color: var(--ink-muted);
}
.steps li span {
  display: grid;
  place-items: center;
  width: 24px;
  height: 24px;
  flex: none;
  border-radius: var(--r-full);
  background: var(--gray-200);
  color: var(--ink-secondary);
  font-size: 12px;
  font-weight: 700;
}
/* 진행 상태를 **색만으로 표시하지 않는다** — 글자 굵기도 함께 바뀐다 */
.steps li.current,
.steps li.done {
  color: var(--navy-700);
  font-weight: 700;
}
.steps li.current span,
.steps li.done span {
  background: var(--brand-500);
  color: #fff;
}

.panel {
  display: flex;
  flex-direction: column;
  gap: var(--sp-6);
}
.block h2 {
  margin: 0 0 var(--sp-3);
  font-size: 14px;
  color: var(--navy-700);
}
.step-hint {
  margin: 0 0 var(--sp-3);
  font-size: 12.5px;
}
.step-hint.center {
  text-align: center;
  margin: var(--sp-2) 0 0;
}

.pick-row,
.chip-row {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: var(--sp-3);
}
.chip-row {
  display: flex;
  flex-wrap: wrap;
}

.pick {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 5px;
  min-height: 108px;
  padding: var(--sp-4) var(--sp-3);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
}
.pick.wide-pick {
  min-height: 74px;
  justify-content: center;
}
.pick:hover:not(:disabled) {
  border-color: var(--brand-300);
}
.pick.active {
  border-color: var(--brand-500);
  background: var(--brand-50);
}
.pick.pending {
  opacity: 0.5;
  cursor: not-allowed;
}
.pick-icon {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: var(--r-full);
  background: var(--brand-50);
  color: var(--brand-600);
}
.pick.pending .pick-icon {
  background: var(--gray-100);
  color: var(--gray-400);
}
.pick-icon svg {
  width: 23px;
  height: 23px;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.pick-label {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--navy-700);
}
.pick-meta {
  font-size: 11.5px;
  color: var(--ink-muted);
}

.disease-chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 40px;
  padding: 8px 18px;
  border: 1px solid var(--line);
  border-radius: var(--r-full);
  background: var(--surface);
  font-size: 13.5px;
  color: var(--ink-secondary);
}
.disease-chip.active {
  border-color: var(--brand-500);
  background: var(--brand-50);
  color: var(--brand-700);
  font-weight: 700;
}
.chip-mark {
  display: inline-grid;
  place-items: center;
  width: 18px;
  height: 18px;
  border-radius: var(--r-full);
  background: var(--brand-500);
  color: #fff;
  font-size: 11px;
}
.disease-chip:not(.active) .chip-mark {
  background: var(--gray-200);
}

.start {
  justify-content: center;
}

.loading {
  padding: var(--sp-8) 0;
}

@media (max-width: 860px) {
  .learn {
    grid-template-columns: 1fr;
  }
  .side {
    position: static;
  }
  .side-help {
    display: none;
  }
}
</style>
