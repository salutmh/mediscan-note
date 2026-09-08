<script setup>
/**
 * 화면 2 — 판독 훈련 (api-spec.md 2-2 / 2-3, 4절 화면 2)
 * + 제출 후 화면 3(결과 비교)·화면 4(학습 해설)를 아래에 이어서 보여준다.
 *   둘 다 submit 응답만 쓰므로 추가 API 호출은 없다.
 *
 * 이 화면은 복습노트 재도전(화면 6)에서도 그대로 재사용한다.
 * 라우트 meta.retry 가 true 면 제출을 POST /api/wrong-notes/{id}/retry 로 보낸다 (응답 형식 동일).
 */
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import { onBeforeRouteUpdate, useRoute } from 'vue-router'
import RoiCanvas from '../components/RoiCanvas.vue'
import ResultCompare from '../components/ResultCompare.vue'
import ExplanationPanel from '../components/ExplanationPanel.vue'
import { ApiError } from '../api/client'
import {
  getCase,
  listCases,
  listWrongNotes,
  markExplanationViewed,
  retryWrongNote,
  submitRoi,
} from '../api/endpoints'
import { useActiveTime } from '../useActiveTime'
import { bodyPartLabel, diseaseLabel } from '../labels'

const route = useRoute()

const caseId = ref(route.params.caseId)
const isRetry = computed(() => route.meta.retry === true)

const caseDetail = ref(null)
const loadError = ref('')
const detailMissing = ref(false) // 케이스 상세를 찾지 못해 기본 캔버스로 진행하는 상태

const roiCanvas = ref(null)
const hasInput = ref(false)

const activeTime = useActiveTime()
const explanationPanel = ref(null)
let explanationObserver = null
let explanationReported = false

/**
 * 해설이 **실제로 화면에 보였을 때** 한 번만 알린다.
 *
 * 해설 블록은 채점 직후 항상 렌더되지만, 사용자가 거기까지 내려봤는지는 다른 이야기다.
 * 렌더 시점에 기록하면 "열람률 100%" 라는 쓸모없는 숫자가 나온다. 알고 싶은 것은
 * "틀린 뒤에 해설을 읽는가" 이고, 그 답이 전문가 소견 작성에 사람 시간을 쓸지를 가른다.
 *
 * 관찰용이라 실패해도 조용히 넘어간다 — 학습 흐름에 영향을 주지 않는다.
 */
function watchExplanationVisibility() {
  stopWatchingExplanation()
  const el = explanationPanel.value?.$el
  if (!el || explanationReported) return
  // 지원하지 않는 환경(오래된 브라우저, 테스트 러너)에서는 그냥 기록하지 않는다.
  if (typeof IntersectionObserver === 'undefined') return

  explanationObserver = new IntersectionObserver(
    (entries) => {
      if (!entries.some((e) => e.isIntersecting)) return
      explanationReported = true
      stopWatchingExplanation()
      markExplanationViewed(caseId.value).catch(() => {})
    },
    { threshold: 0.3 },
  )
  explanationObserver.observe(el)
}

onBeforeUnmount(stopWatchingExplanation)

function stopWatchingExplanation() {
  explanationObserver?.disconnect()
  explanationObserver = null
}
const phase = ref('idle') // 'idle' | 'submitting' | 'done'
const result = ref(null)
const submitError = ref('')
const submittedMaskDataUrl = ref(null)

const locked = computed(() => phase.value !== 'idle')
// 기준 마스크가 없는 케이스는 채점할 수 없다 (api-spec v0.4) — 제출 자체를 막는다
const gradable = computed(() => caseDetail.value?.gradable !== false)
const meta = computed(() => meta_(caseDetail.value))
function meta_(detail) {
  return detail?.image_meta ?? {}
}
const canvasWidth = computed(() => meta.value.width ?? 512)
const canvasHeight = computed(() => meta.value.height ?? 512)

/**
 * slice 탐색 (v0.6)
 *
 * 병변은 여러 slice 에 걸쳐 있다. 한 장만 보여주면 "찾는" 훈련이 아니라
 * "주어진 그림에서 밝은 덩어리 칠하기"가 된다. 그래서 등록된 slice 를 넘겨볼 수 있게 한다.
 *
 * **ROI 입력과 채점은 대표 slice 에서만 한다.** 채점 기준(전문가 GT)이 대표 slice 기준으로
 * 고정돼 있기 때문이다. 다른 slice 에서는 캔버스를 잠그고 무엇을 해야 하는지 알려준다.
 * (slice 별 채점은 채점 계약을 바꾸는 일이라 별도 설계가 필요하다 — CLAUDE_HANDOFF 참고)
 *
 * 서버는 **어느 slice 에 마스크가 있는지 알려주지 않는다.** 그게 곧 정답 위치다.
 */
const slices = computed(() => caseDetail.value?.slices ?? [])
const hasSlices = computed(() => slices.value.length > 1)
const sliceCursor = ref(0) // slices 배열의 인덱스 (원본 slice_index 가 아니다)

const currentSlice = computed(() => slices.value[sliceCursor.value] ?? null)
const representativeSlice = computed(
  () => caseDetail.value?.representative_slice ?? meta.value.slice_index ?? null,
)
const onRepresentative = computed(
  () => !hasSlices.value || currentSlice.value?.slice_index === representativeSlice.value,
)
/** 지금 화면에 그릴 영상. slice 를 넘기면 그 slice 이미지로 바뀐다. */
const viewerImageUrl = computed(
  () => currentSlice.value?.image_url ?? caseDetail.value?.image_url ?? null,
)

function goToRepresentative() {
  const index = slices.value.findIndex((s) => s.slice_index === representativeSlice.value)
  if (index >= 0) sliceCursor.value = index
}

function stepSlice(delta) {
  const next = sliceCursor.value + delta
  if (next >= 0 && next < slices.value.length) sliceCursor.value = next
}

async function load() {
  activeTime.reset() // 케이스가 바뀌면 시계도 새로 시작한다
  explanationReported = false
  stopWatchingExplanation()
  caseDetail.value = null
  loadError.value = ''
  detailMissing.value = false
  resetSubmission()
  try {
    const data = await getCase(caseId.value)
    caseDetail.value = data
    // 처음에는 대표 slice 를 보여준다 (여기서만 ROI 를 그릴 수 있다)
    goToRepresentative()
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) {
      // 등록되지 않은 case_id (예: 삭제된 케이스의 오래된 링크). 흐름이 막히지 않게 안내만 띄운다.
      detailMissing.value = true
      caseDetail.value = {
        case_id: caseId.value,
        body_part: null,
        disease: null,
        image_url: null,
        image_meta: { width: 512, height: 512, slice_index: 0, total_slices: 1 },
      }
    } else {
      loadError.value = e.message
    }
  }
}

function resetSubmission() {
  result.value = null
  submitError.value = ''
  submittedMaskDataUrl.value = null
  phase.value = 'idle'
  nextTarget.value = null
}

function onRoiChange(state) {
  hasInput.value = state.hasInput
}

async function onSubmit() {
  if (!hasInput.value || locked.value) return
  // 제출은 "대표 slice 에 대한 내 답"이다. 다른 slice 를 보던 중이었다면 대표로 되돌린다 —
  // 그래야 아래 결과 오버레이(대표 slice 기준)와 화면이 어긋나지 않는다.
  goToRepresentative()
  phase.value = 'submitting'
  submitError.value = ''
  try {
    const roi = {
      // 판독훈련은 브러시로 칠한 영역만 받는다 (api-spec v0.4 ROI 입력 표)
      type: 'brush_mask',
      points: roiCanvas.value.getPoints(),
      mask_png_base64: roiCanvas.value.getMaskBase64(),
    }
    // 결과 비교 화면에서 내 ROI 를 그대로 겹쳐 보여주기 위해 제출한 마스크를 붙잡아 둔다.
    submittedMaskDataUrl.value = roiCanvas.value.getMaskDataUrl()
    // 이 케이스를 보고 있던 시간. 운영자 화면의 "평균 소요 시간"이 이 값으로 채워진다
    // (지금까지는 아무도 보내지 않아 항상 비어 있었다).
    const seconds = activeTime.elapsedSeconds()
    result.value = isRetry.value
      ? await retryWrongNote(caseId.value, roi, seconds)
      : await submitRoi(caseId.value, roi, seconds)
    phase.value = 'done'
    findNextTarget()
    // 해설 블록이 DOM 에 올라온 뒤에 관찰을 건다
    await nextTick()
    watchExplanationVisibility()
  } catch (e) {
    submitError.value = e.message
    phase.value = 'idle'
  }
}

function retry() {
  resetSubmission()
  roiCanvas.value?.clear()
  activeTime.reset() // 재도전은 새로운 시도다 — 앞선 시도의 시간을 얹지 않는다
}

/**
 * 채점이 끝난 뒤 "다음에 무엇을 할지"를 제시한다.
 *
 * 이게 없으면 학습 루프가 닫히지 않는다 — 한 케이스를 끝낼 때마다 사용자가 직접
 * 목록으로 되돌아가야 하고, 그 지점에서 세션이 끊긴다.
 *
 * 판독훈련이면 **아직 학습완료가 아닌 다음 케이스**를, 재도전이면 **남은 복습 케이스**를 고른다.
 * 목록 조회가 실패해도 결과 화면은 그대로 보여야 하므로 조용히 넘어간다(버튼만 안 나온다).
 */
const nextTarget = ref(null)

async function findNextTarget() {
  nextTarget.value = null
  try {
    if (isRetry.value) {
      const items = (await listWrongNotes()).items.filter((i) => i.case_id !== caseId.value)
      if (items.length) {
        nextTarget.value = {
          caseId: items[0].case_id,
          label: '다음 복습 케이스',
          to: { name: 'retry', params: { caseId: items[0].case_id } },
          remaining: items.length,
        }
      }
      return
    }
    const cases = (await listCases()).cases
    const remaining = cases.filter((c) => !c.has_matched && c.case_id !== caseId.value)
    if (remaining.length) {
      nextTarget.value = {
        caseId: remaining[0].case_id,
        label: '다음 케이스',
        to: { name: 'reading', params: { caseId: remaining[0].case_id } },
        remaining: remaining.length,
      }
    }
  } catch {
    // 결과 화면을 막을 이유가 없다 — 다음 행동 버튼만 생략된다
    nextTarget.value = null
  }
}

load()
// 같은 컴포넌트를 쓰는 라우트끼리 이동할 때(다른 케이스로 재도전 등) 다시 로드
onBeforeRouteUpdate((to) => {
  caseId.value = to.params.caseId
  load()
})
</script>

<template>
  <RouterLink v-if="isRetry" to="/wrong-notes" class="back">← 복습노트</RouterLink>
  <RouterLink v-else to="/cases" class="back">← 케이스 목록</RouterLink>

  <p v-if="loadError" class="error">{{ loadError }}</p>
  <p v-else-if="!caseDetail" class="muted loading">케이스를 불러오는 중...</p>

  <template v-else>
    <header class="head">
      <div class="titles">
        <h1>{{ caseDetail.case_id }}</h1>
        <p v-if="caseDetail.body_part" class="lead">
          {{ bodyPartLabel(caseDetail.body_part) }}
          <span class="dot">·</span>
          {{ diseaseLabel(caseDetail.disease) }}
        </p>
      </div>
      <span v-if="isRetry" class="badge partial_match">재도전</span>
    </header>

    <p v-if="detailMissing" class="notice">
      이 케이스({{ caseDetail.case_id }})를 찾을 수 없어 영상 없이 기본 512×512 캔버스로 진행합니다.
      등록되지 않았거나 삭제된 케이스일 수 있습니다 — 케이스 목록에서 다시 선택해 주세요.
    </p>

    <div class="layout">
      <div class="viewer-col">
        <RoiCanvas
          ref="roiCanvas"
          :image-url="viewerImageUrl"
          :width="canvasWidth"
          :height="canvasHeight"
          :disabled="locked || !onRepresentative"
          :clear-on-image-change="false"
          @change="onRoiChange"
        />

        <div v-if="hasSlices" class="slices card">
          <div class="slice-bar">
            <button
              class="sm"
              :disabled="sliceCursor === 0"
              aria-label="이전 슬라이스"
              @click="stepSlice(-1)"
            >
              ‹
            </button>
            <input
              type="range"
              min="0"
              :max="slices.length - 1"
              v-model.number="sliceCursor"
              aria-label="슬라이스 이동"
            />
            <button
              class="sm"
              :disabled="sliceCursor === slices.length - 1"
              aria-label="다음 슬라이스"
              @click="stepSlice(1)"
            >
              ›
            </button>
            <strong class="tnum slice-label">
              slice {{ currentSlice?.slice_index }}
              <span v-if="onRepresentative" class="rep-tag">대표</span>
            </strong>
          </div>

          <div v-if="!onRepresentative" class="notice slice-locked">
            <p>
              지금은 <strong>slice {{ currentSlice?.slice_index }}</strong> 를 살펴보는 중입니다.
              표시(ROI) 입력과 채점은 <strong>대표 slice {{ representativeSlice }}</strong> 에서만 합니다
              — 칠하던 표시는 그대로 남아 있습니다.
            </p>
            <button class="sm" @click="goToRepresentative">대표 slice로 이동</button>
          </div>
          <p v-else class="muted">
            병변은 여러 slice 에 걸쳐 있습니다. 좌우로 넘겨 범위를 확인한 뒤
            이 대표 slice 에 표시하세요. 번호는 <strong>원본 volume 인덱스</strong>라 학습 해설의
            slice 번호와 같습니다 (이 케이스는 병변 주변
            {{ slices.length }}장이 등록되어 있습니다 / 원본 {{ meta.total_slices }}장).
          </p>
        </div>
      </div>

      <aside class="side">
        <div class="card submit-card">
          <div class="card-title">
            <h2>ROI 제출</h2>
            <span class="badge" :class="{ match: phase === 'done' }">
              {{ phase === 'idle' ? '입력 중' : phase === 'submitting' ? '채점 중' : '제출 완료' }}
            </span>
          </div>

          <ol class="steps">
            <li :class="{ done: hasInput }">이상으로 판단되는 부위를 칠하기</li>
            <li :class="{ done: phase === 'done' }">제출하고 기준 마스크와 비교</li>
          </ol>

          <p v-if="!gradable" class="notice">
            이 케이스는 검수된 기준 마스크가 아직 등록되지 않아 채점할 수 없습니다.
            다른 케이스를 먼저 풀어주세요.
          </p>

          <p v-if="submitError" class="error">{{ submitError }}</p>

          <button
            v-if="phase !== 'done'"
            class="primary lg wide"
            :disabled="!hasInput || !gradable || phase === 'submitting'"
            @click="onSubmit"
          >
            {{ phase === 'submitting' ? '채점 중...' : '제출' }}
          </button>
          <template v-else>
            <!-- 학습 루프를 닫는다: 끝냈으면 다음에 무엇을 할지 바로 제시한다 -->
            <RouterLink
              v-if="nextTarget"
              :to="nextTarget.to"
              class="btn primary lg wide next-action"
            >
              {{ nextTarget.label }} →
            </RouterLink>
            <button class="lg wide" @click="retry">다시 풀기</button>
            <RouterLink
              :to="isRetry ? '/wrong-notes' : '/cases'"
              class="btn lg wide next-action"
            >
              {{ isRetry ? '복습노트로' : '케이스 목록으로' }}
            </RouterLink>
            <p v-if="nextTarget" class="muted hint">
              {{ isRetry ? '복습할 케이스' : '아직 학습완료가 아닌 케이스' }}
              {{ nextTarget.remaining }}개가 남아 있습니다.
            </p>
            <p v-else class="muted hint">
              {{ isRetry ? '복습할 케이스를 모두 마쳤습니다.' : '모든 케이스를 학습완료했습니다.' }}
            </p>
          </template>

          <p v-if="gradable && !hasInput && phase === 'idle'" class="muted hint">
            영역을 먼저 칠해야 제출할 수 있습니다.
          </p>
        </div>
      </aside>
    </div>

    <!-- 화면 3 + 화면 4 — submit 응답만으로 구성 -->
    <template v-if="result">
      <ResultCompare
        class="stack"
        :result="result"
        :user-mask-data-url="submittedMaskDataUrl"
        :base-image-url="caseDetail.image_url"
        :width="canvasWidth"
        :height="canvasHeight"
      />
      <ExplanationPanel
        v-if="result.explanation"
        ref="explanationPanel"
        class="stack"
        :explanation="result.explanation"
      />
    </template>
  </template>
</template>

<style scoped>
.back {
  display: inline-block;
  margin-bottom: var(--sp-4);
  color: var(--ink-muted);
  font-size: 13.5px;
  text-decoration: none;
}

.back:hover {
  color: var(--brand-600);
}

.loading {
  padding: var(--sp-8) 0;
}

.head {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
  margin-bottom: var(--sp-5);
}

.head h1 {
  margin-bottom: 2px;
}

.dot {
  color: var(--gray-300);
  margin: 0 2px;
}

.layout {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-5);
  align-items: flex-start;
}

.viewer-col {
  flex: 1 1 460px;
  min-width: 300px;
}

.side {
  flex: 0 0 270px;
  position: sticky;
  top: 76px;
}

.slices {
  margin-top: var(--sp-4);
  max-width: 560px;
  padding: var(--sp-4);
}

.slice-bar {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  font-size: 13.5px;
}

.slice-bar button {
  padding: 2px 10px;
  font-size: 16px;
  line-height: 1.2;
}

.slice-label {
  min-width: 96px;
  text-align: right;
}

/* 대표 slice 에서만 ROI 를 그릴 수 있다는 것을 한눈에 */
.rep-tag {
  margin-left: 4px;
  padding: 1px 6px;
  border-radius: var(--r-full);
  background: var(--match-bg);
  border: 1px solid var(--match-line);
  color: var(--match-ink);
  font-size: 10.5px;
  font-weight: 700;
}

.slice-locked {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  flex-wrap: wrap;
}

/* 버튼이 문장 중간에서 줄을 끊지 않도록 문단과 분리한다 */
.slice-locked p {
  margin: 0;
  flex: 1 1 260px;
}

.slice-locked button {
  flex: 0 0 auto;
}

/* 채점 후 다음 행동 — RouterLink 라 .btn 을 쓰고, 버튼과 같은 폭으로 맞춘다 */
.next-action {
  display: block;
  width: 100%;
  text-align: center;
  text-decoration: none;
  margin-bottom: var(--sp-2);
}

.slices input[type='range'] {
  flex: 1;
}

.slices strong {
  font-size: 13px;
  color: var(--ink-secondary);
}

.slices .muted {
  margin-top: var(--sp-2);
  font-size: 12px;
}

.steps {
  list-style: none;
  counter-reset: step;
  padding: 0;
  margin: 0 0 var(--sp-4);
}

.steps li {
  counter-increment: step;
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
  padding: 5px 0;
  color: var(--ink-muted);
  font-size: 13px;
  line-height: 1.5;
}

.steps li::before {
  content: counter(step);
  flex: 0 0 auto;
  display: grid;
  place-items: center;
  width: 18px;
  height: 18px;
  margin-top: 1px;
  border-radius: var(--r-full);
  border: 1px solid var(--line-strong);
  font-size: 11px;
  font-weight: 700;
}

.steps li.done {
  color: var(--match-ink);
}

.steps li.done::before {
  content: '✓';
  background: var(--match-bg);
  border-color: var(--match-line);
  color: var(--match-ink);
}

.wide {
  width: 100%;
}

.hint {
  margin-top: var(--sp-2);
  text-align: center;
  font-size: 12px;
}

.stack {
  display: block;
  margin-top: var(--sp-5);
}

@media (max-width: 860px) {
  .side {
    position: static;
    flex: 1 1 100%;
  }
}
</style>
