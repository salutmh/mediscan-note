<script setup>
/**
 * 화면 5 — AI 설명 영역 / 사용자 의료영상 분석 (api-spec.md 2-6, 4절 화면 5)
 *
 * 업로드 -> 영역 지정(ROI) -> POST /api/analyze -> candidate_diseases / key_findings 표시.
 * disclaimer 문구는 화면 상단에 항상 고정한다(검토노트 5번 항목).
 *
 * 참고: api-spec.md 2-6 의 region 예시는 { type, points } 뿐이라 그 형태 그대로 보낸다.
 * 모델이 마스크까지 필요하면 2-3(submit)처럼 region.mask_png_base64 를 스펙에 추가해야 한다 (팀 확인 필요).
 */
import { computed, onMounted, ref } from 'vue'
import RoiCanvas from '../components/RoiCanvas.vue'
import { analyzeAvailability, analyzeImage } from '../api/endpoints'

// 서버 응답 전에도 고지 문구가 비어 보이지 않게 쓰는 기본값. 분석 후에는 응답의 disclaimer 로 대체된다.
const DEFAULT_DISCLAIMER = '본 결과는 학습 참고용 AI 분석이며 확정 진단이 아닙니다.'

// 아래 제한은 서버(app/uploads.py)와 같은 값이다.
// **판정 권한은 서버에 있고**, 여기 검사는 업로드 전에 바로 알려주기 위한 UX 용이다.
const MAX_BYTES = 12 * 1024 * 1024
const MIN_DIMENSION = 64
const MAX_DIMENSION = 4096
const ALLOWED_TYPES = ['image/png', 'image/jpeg']

const imageDataUrl = ref(null)
const imageName = ref('')
const imageSize = ref({ width: 512, height: 512 })
const fileError = ref('')
const dragging = ref(false)

const roiCanvas = ref(null)
const hasInput = ref(false)

const phase = ref('idle') // 'idle' | 'analyzing' | 'done'
const result = ref(null)

/**
 * 분석 가능 여부를 **미리** 확인한다.
 *
 * 예전에는 화면 문구에 "준비 중"을 하드코딩해두고, 사용자가 영상을 올리고 ROI 를 칠하고
 * 요청까지 한 뒤에야 서버가 model_unavailable 을 돌려줬다. 그 노력이 통째로 낭비된다.
 * 모델이 준비되면 문구가 반대로 거짓말을 하게 되는 문제도 있었다.
 *
 * 조회에 실패하면 **막지 않는다** — 확인을 못 했다고 기능을 잠그면 더 나쁘다.
 * 그 경우 서버가 요청 시점에 사실대로 답한다.
 */
const availability = ref(null)
const analysisBlocked = computed(() => availability.value?.available === false)

onMounted(async () => {
  try {
    availability.value = await analyzeAvailability()
  } catch {
    availability.value = null
  }
})
const analyzeError = ref('')

const disclaimer = computed(() => result.value?.disclaimer ?? DEFAULT_DISCLAIMER)
const locked = computed(() => phase.value !== 'idle')

function readFile(file) {
  if (!file) return
  fileError.value = ''
  if (!ALLOWED_TYPES.includes(file.type)) {
    fileError.value = 'PNG 또는 JPEG 파일만 업로드할 수 있습니다. (DICOM 은 추후 지원)'
    return
  }
  if (file.size > MAX_BYTES) {
    fileError.value = `파일이 너무 큽니다. 최대 ${MAX_BYTES / (1024 * 1024)}MB 까지 업로드할 수 있습니다.`
    return
  }
  const reader = new FileReader()
  reader.onload = () => {
    const dataUrl = reader.result
    const img = new Image()
    img.onload = () => {
      const { naturalWidth: w, naturalHeight: h } = img
      if (w < MIN_DIMENSION || h < MIN_DIMENSION) {
        fileError.value = `이미지가 너무 작습니다. 최소 ${MIN_DIMENSION}×${MIN_DIMENSION} 이상이어야 합니다.`
        return
      }
      if (w > MAX_DIMENSION || h > MAX_DIMENSION) {
        fileError.value = `이미지가 너무 큽니다. 최대 ${MAX_DIMENSION}×${MAX_DIMENSION} 까지 지원합니다.`
        return
      }
      imageSize.value = { width: w, height: h }
      imageDataUrl.value = dataUrl
      imageName.value = file.name
      result.value = null
      analyzeError.value = ''
      phase.value = 'idle'
    }
    img.onerror = () => {
      fileError.value = '이미지를 읽을 수 없습니다.'
    }
    img.src = dataUrl
  }
  reader.onerror = () => {
    fileError.value = '파일을 읽는 중 오류가 발생했습니다.'
  }
  reader.readAsDataURL(file)
}

function onFileChange(event) {
  readFile(event.target.files?.[0])
}

function onDrop(event) {
  dragging.value = false
  if (locked.value) return
  readFile(event.dataTransfer?.files?.[0])
}

function onRoiChange(state) {
  hasInput.value = state.hasInput
}

async function onAnalyze() {
  if (!imageDataUrl.value || !hasInput.value || locked.value) return
  phase.value = 'analyzing'
  analyzeError.value = ''
  try {
    result.value = await analyzeImage({
      image_base64: imageDataUrl.value.split(',')[1],
      region: { type: 'brush_mask', points: roiCanvas.value.getPoints() },
    })
    phase.value = 'done'
  } catch (e) {
    analyzeError.value = e.message
    phase.value = 'idle'
  }
}

function reset() {
  result.value = null
  analyzeError.value = ''
  phase.value = 'idle'
  roiCanvas.value?.clear()
}

function percent(p) {
  return `${Math.round(p * 1000) / 10}%`
}
</script>

<template>
  <!-- disclaimer 상단 고정. 헤더처럼 화면 폭 전체를 채워야 "고정 띠"로 읽힌다 -->
  <div class="disclaimer">
    <span class="inner">
      <span class="icon" aria-hidden="true">⚠</span>
      <span>{{ disclaimer }}</span>
    </span>
  </div>

  <header class="head">
    <h1>내 영상 AI 분석</h1>
    <!-- 준비 상태를 서버에 물어서 표시한다. 화면에 하드코딩하면 모델이 준비된 뒤에
         반대로 거짓말을 하게 된다. -->
    <p v-if="analysisBlocked" class="lead">
      <strong>이 화면의 AI 분석 기능은 아직 준비되지 않았습니다.</strong>
      아래에서 영상 업로드와 영역 지정은 해보실 수 있지만, <strong>분석 결과는 제공되지 않습니다.</strong>
      업로드한 영상은 서버에 저장되지 않고, 촬영기기 정보 등 메타데이터는 제거됩니다.
    </p>
    <p v-else class="lead">
      영상을 올리고 확인하고 싶은 부위를 표시하면 AI 분석 결과를 보여드립니다.
      업로드한 영상은 서버에 저장되지 않고 분석에만 사용되며, 촬영기기 정보 등 메타데이터는 제거됩니다.
    </p>

    <p v-if="analysisBlocked && availability?.unavailable_reason" class="notice blocked-reason">
      {{ availability.unavailable_reason }}
    </p>
  </header>

  <!-- 업로드 -->
  <label
    class="dropzone"
    :class="{ dragging, compact: imageDataUrl }"
    @dragover.prevent="dragging = true"
    @dragleave.prevent="dragging = false"
    @drop.prevent="onDrop"
  >
    <input type="file" accept="image/png,image/jpeg" @change="onFileChange" :disabled="phase === 'analyzing'" />
    <template v-if="!imageDataUrl">
      <strong>영상 파일을 끌어다 놓거나 클릭해서 선택</strong>
      <span class="muted">PNG · JPEG · 최대 12MB · 64~4096px (DICOM 은 추후 지원)</span>
    </template>
    <template v-else>
      <strong class="fname">{{ imageName }}</strong>
      <span class="muted tnum">{{ imageSize.width }} × {{ imageSize.height }} · 다른 영상 선택</span>
    </template>
  </label>

  <p v-if="fileError" class="error">{{ fileError }}</p>

  <!-- 업로드 전에는 위 드롭존이 안내를 겸하므로 별도 빈 카드는 두지 않는다 -->
  <p v-if="!imageDataUrl" class="muted hint">
    판독 훈련용 케이스와 달리, 이 화면은 내가 가진 영상을 분석하는 트랙입니다.
  </p>

  <div v-else class="layout">
    <div class="viewer-col">
      <RoiCanvas
        ref="roiCanvas"
        :image-url="imageDataUrl"
        :width="imageSize.width"
        :height="imageSize.height"
        :disabled="locked"
        :tools="['brush', 'eraser']"
        @change="onRoiChange"
      />
    </div>

    <aside class="side">
      <div class="card">
        <div class="card-title">
          <h2>분석 요청</h2>
          <span class="badge" :class="{ match: phase === 'done' }">
            {{ phase === 'idle' ? '영역 지정' : phase === 'analyzing' ? '요청 중' : '요청 완료' }}
          </span>
        </div>
        <p class="muted">
          {{ locked ? '요청이 끝나 입력이 잠겼습니다.' : '분석할 영역을 표시한 뒤 요청하세요.' }}
        </p>
        <p v-if="analyzeError" class="error">{{ analyzeError }}</p>
        <button
          v-if="phase !== 'done'"
          class="primary lg wide"
          :disabled="!hasInput || phase === 'analyzing' || analysisBlocked"
          @click="onAnalyze"
        >
          {{
            analysisBlocked
              ? '분석 준비 중'
              : phase === 'analyzing'
                ? '분석 중...'
                : 'AI 분석 요청'
          }}
        </button>

        <p v-if="analysisBlocked" class="muted hint">
          단일 이미지용 분석 모델이 준비되면 이 버튼이 활성화됩니다.
          지금은 업로드와 영역 지정까지만 확인하실 수 있습니다.
        </p>
        <button v-else class="lg wide" @click="reset">영역 다시 지정</button>
      </div>

      <div v-if="result" class="card">
        <div class="card-title">
          <h2>AI 분석 결과</h2>
          <span v-if="result.model_version" class="muted">model {{ result.model_version }}</span>
        </div>

        <!-- 모델이 없을 때 소견을 지어내지 않는다. 왜 못 하는지만 밝힌다 (api-spec 2-6) -->
        <p v-if="result.status === 'model_unavailable'" class="state unavailable">
          <strong>아직 이 영상을 분석할 수 있는 AI 모델이 연결되지 않았습니다.</strong>
          {{ result.unavailable_reason }}
          업로드한 영상은 검증만 거쳤고 저장되지 않았습니다.
        </p>
        <p v-else-if="result.is_demo" class="state demo">
          <strong>화면 확인용 예시 데이터입니다.</strong>
          아래 내용은 업로드한 영상을 실제로 분석한 결과가 아닙니다.
        </p>

        <template v-if="result.status !== 'model_unavailable'">
        <div class="field">
          <span class="label">의심 영역</span>
          <strong class="region">{{ result.suspected_region }}</strong>
        </div>
        <div class="field">
          <span class="label">주요 소견</span>
          <p class="findings">{{ result.key_findings }}</p>
        </div>

        <div class="field">
          <span class="label">추정 질환</span>
          <ul class="diseases">
            <li v-for="(d, i) in result.candidate_diseases" :key="d.name">
              <div class="d-head">
                <span class="d-name">{{ d.name }}</span>
                <span class="prob tnum">{{ percent(d.probability) }}</span>
              </div>
              <div class="track">
                <div class="fill" :class="{ top: i === 0 }" :style="{ width: percent(d.probability) }"></div>
              </div>
            </li>
          </ul>
        </div>

        <p v-if="result.ai_mask_url" class="muted mask">기준 마스크: {{ result.ai_mask_url }}</p>
        </template>
      </div>
    </aside>
  </div>
</template>

<style scoped>
/* 좌우로 뷰포트 끝까지 늘리고(full-bleed), 내부 텍스트는 본문과 같은 폭에 맞춘다 */
.state {
  margin: 0 0 var(--sp-4);
  padding: var(--sp-3) var(--sp-4);
  border-radius: var(--r-md);
  font-size: 13px;
  line-height: 1.6;
}

.state strong {
  display: block;
  margin-bottom: 2px;
}

.state.unavailable {
  background: var(--surface-sunken);
  border: 1px solid var(--line-strong);
  color: var(--ink-secondary);
}

.blocked-reason {
  margin-top: var(--sp-3);
  font-size: 12.5px;
}

.state.demo {
  background: var(--partial-bg);
  border: 1px solid var(--partial-line);
  color: var(--partial-ink);
}

.disclaimer {
  position: sticky;
  top: 51px;
  z-index: 10;
  margin: calc(var(--sp-8) * -1) calc(50% - 50vw) var(--sp-5);
  padding: 11px var(--sp-5);
  background: var(--partial-bg);
  border-bottom: 1px solid var(--partial-line);
  color: var(--partial-ink);
  font-size: 13px;
  font-weight: 600;
}

.disclaimer .inner {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  max-width: 1040px;
  margin: 0 auto;
}

.disclaimer .icon {
  font-size: 14px;
}

/* 좁은 화면에서는 헤더가 두 줄로 늘어나 sticky 위치가 어긋나므로 고정을 해제한다 */
@media (max-width: 760px) {
  .disclaimer {
    position: static;
    margin-top: calc(var(--sp-5) * -1);
  }
}

.head {
  margin-bottom: var(--sp-5);
}

.head h1 {
  margin-bottom: 4px;
}

.head .lead {
  max-width: 620px;
}

/* 업로드 영역 */
.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: var(--sp-8) var(--sp-5);
  margin-bottom: var(--sp-4);
  border: 1.5px dashed var(--line-strong);
  border-radius: var(--r-lg);
  background: var(--surface);
  text-align: center;
  cursor: pointer;
  transition: border-color var(--transition), background var(--transition);
}

.dropzone:hover {
  border-color: var(--brand-300);
  background: var(--brand-50);
}

.dropzone.dragging {
  border-color: var(--brand-500);
  background: var(--brand-50);
}

.dropzone.compact {
  padding: var(--sp-4);
  flex-direction: row;
  gap: var(--sp-3);
  justify-content: flex-start;
  text-align: left;
}

.dropzone input[type='file'] {
  display: none;
}

.dropzone strong {
  font-size: 14px;
}

.fname {
  max-width: 320px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.hint {
  text-align: center;
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
  flex: 0 0 300px;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.wide {
  width: 100%;
  margin-top: var(--sp-3);
}

.field {
  padding: var(--sp-3) 0;
  border-top: 1px solid var(--line);
}

.field:first-of-type {
  border-top: 0;
  padding-top: 0;
}

.label {
  display: block;
  color: var(--ink-muted);
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 3px;
}

.region {
  font-size: 15px;
}

.findings {
  font-size: 13.5px;
  line-height: 1.6;
  color: var(--ink-secondary);
}

.diseases {
  list-style: none;
  padding: 0;
  margin: var(--sp-2) 0 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.d-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--sp-2);
  margin-bottom: 4px;
}

.d-name {
  font-size: 13.5px;
  font-weight: 500;
}

.prob {
  font-size: 13px;
  font-weight: 600;
  color: var(--ink-secondary);
}

.track {
  height: 7px;
  background: var(--gray-100);
  border-radius: var(--r-full);
  overflow: hidden;
}

.fill {
  height: 100%;
  border-radius: 0 4px 4px 0;
  background: var(--brand-300);
  min-width: 2px;
}

/* 1순위 후보만 진하게 — 순위가 색으로도 읽히게 */
.fill.top {
  background: var(--brand-500);
}

.mask {
  margin-top: var(--sp-3);
  font-size: 12px;
}

@media (max-width: 860px) {
  .side {
    flex: 1 1 100%;
  }
}
</style>
