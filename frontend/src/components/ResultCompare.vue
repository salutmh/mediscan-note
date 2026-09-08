<script setup>
/**
 * 화면 3 — 결과 비교 (api-spec.md 4절 화면 3)
 *
 * grade 뱃지 + dice/iou/location_score 수치 + 사용자 ROI vs 기준 마스크 오버레이.
 * 별도 API 호출 없이 submit(2-3) 응답만 사용한다.
 *
 * 오버레이는 두 마스크의 픽셀을 직접 합성해서 색을 나눈다:
 *   사용자만=파랑, 기준만=초록, 겹침=노랑 (화면 정의서의 색상 규칙)
 * 기준 마스크가 다른 도메인에서 오면(백엔드가 별도 포트에서 서빙)
 * canvas 가 오염돼 getImageData 가 막히므로, 그 경우엔 두 마스크를 반투명하게
 * 겹쳐 보여주는 방식으로 자동 폴백한다.
 */
import { computed, onMounted, ref, watch } from 'vue'

const props = defineProps({
  result: { type: Object, required: true },
  userMaskDataUrl: { type: String, default: null },
  baseImageUrl: { type: String, default: null },
  width: { type: Number, default: 512 },
  height: { type: Number, default: 512 },
})

const GRADE_LABEL = { match: '일치', partial_match: '부분 일치', mismatch: '불일치' }

// v0.3 이후: 채점 기준은 전문가 검수 reference mask (이전 ai_mask_url)
const referenceMaskUrl = computed(() => props.result.reference_mask_url ?? null)
const aiPrediction = computed(() => props.result.ai_prediction ?? null)
const isProvisional = computed(() => props.result.evaluation?.is_provisional === true)
const evaluationMethod = computed(() => props.result.evaluation?.method ?? 'reference_mask')
const GRADE_DESC = {
  match: '표시한 영역이 기준 마스크와 잘 겹칩니다.',
  partial_match: '일부만 겹칩니다. 아래 오버레이에서 빠진 영역을 확인해보세요.',
  mismatch: '기준 마스크와 겹치는 부분이 거의 없습니다.',
}

// 오버레이 캔버스와 배경 영상이 어긋나지 않게 뷰어 박스를 원본 비율로 맞춘다.
const aspectRatio = computed(() => `${props.width} / ${props.height}`)

const outCanvas = ref(null)
const showUser = ref(true)
const showAi = ref(true)
const pixelMode = ref(true) // false 면 CSS 겹치기 폴백
const overlayNote = ref('')

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.onload = () => resolve(img)
    img.onerror = () => reject(new Error(`이미지를 불러올 수 없습니다: ${src}`))
    img.src = src
  })
}

/**
 * 마스크 이미지를 0/1 비트맵으로 바꾼다.
 * 마스크 PNG 가 "투명 배경 + 불투명 마스크" 형태일 수도, "검은 배경 + 흰 마스크"
 * 형태일 수도 있어서 둘 다 처리한다.
 */
function toMaskBits(img, w, h) {
  const c = document.createElement('canvas')
  c.width = w
  c.height = h
  const ctx = c.getContext('2d')
  ctx.drawImage(img, 0, 0, w, h)
  const { data } = ctx.getImageData(0, 0, w, h) // 오염된 canvas 면 SecurityError

  let hasTransparency = false
  for (let i = 3; i < data.length; i += 4 * 97) {
    if (data[i] < 250) {
      hasTransparency = true
      break
    }
  }

  const bits = new Uint8Array(w * h)
  for (let p = 0; p < w * h; p += 1) {
    const i = p * 4
    bits[p] = hasTransparency
      ? data[i + 3] > 16
        ? 1
        : 0
      : (data[i] + data[i + 1] + data[i + 2]) / 3 > 64
        ? 1
        : 0
  }
  return bits
}

// style.css 의 --roi-* 토큰과 같은 값 (레전드 색과 캔버스 색이 어긋나지 않게)
const COLOR = {
  both: [250, 204, 21, 205], // 겹침 = 노랑
  user: [47, 98, 232, 175], // 사용자 = 파랑
  ai: [16, 185, 129, 175], // 기준 = 초록
}

async function render() {
  if (!outCanvas.value) return
  const w = props.width
  const h = props.height
  outCanvas.value.width = w
  outCanvas.value.height = h
  const ctx = outCanvas.value.getContext('2d')
  ctx.clearRect(0, 0, w, h)
  overlayNote.value = ''

  let userBits = null
  let aiBits = null

  try {
    // 채점과 동일하게 보정 없이 그대로 비교해 그린다 (v0.3에서 fill 보정 제거)
    if (props.userMaskDataUrl) userBits = toMaskBits(await loadImage(props.userMaskDataUrl), w, h)
    if (referenceMaskUrl.value) aiBits = toMaskBits(await loadImage(referenceMaskUrl.value), w, h)
  } catch {
    // 기준 마스크가 없거나(404) 다른 도메인이면 폴백
    pixelMode.value = false
    overlayNote.value =
      `기준 마스크(${referenceMaskUrl.value})를 픽셀 단위로 읽지 못해 반투명 겹치기로 표시합니다. ` +
      '(이미지가 없거나 다른 도메인에서 서빙되는 경우 — 백엔드에서 CORS 허용 헤더를 주면 정확한 겹침 색상이 나옵니다.)'
    return
  }

  if (!userBits && !aiBits) {
    overlayNote.value = '표시할 마스크가 없습니다.'
    return
  }

  const out = ctx.createImageData(w, h)
  for (let p = 0; p < w * h; p += 1) {
    const u = showUser.value && userBits ? userBits[p] : 0
    const a = showAi.value && aiBits ? aiBits[p] : 0
    if (!u && !a) continue
    const color = u && a ? COLOR.both : u ? COLOR.user : COLOR.ai
    const i = p * 4
    out.data[i] = color[0]
    out.data[i + 1] = color[1]
    out.data[i + 2] = color[2]
    out.data[i + 3] = color[3]
  }
  ctx.putImageData(out, 0, 0)
}

onMounted(render)
watch(() => [props.result, props.userMaskDataUrl, showUser.value, showAi.value], render)

/** Dice·IoU 는 0~1, location_score 는 0~100 — 막대 길이용으로 통일 */
function ratio(value, max = 1) {
  const v = Number(value)
  if (!Number.isFinite(v)) return 0
  return Math.max(0, Math.min(100, (v / max) * 100))
}
</script>

<template>
  <section class="card">
    <div class="card-title">
      <h2>결과 비교</h2>
      <span class="muted">
        {{ evaluationMethod === 'reference_mask' ? '기준 마스크 대조' : '좌표 근사(임시)' }}
      </span>
    </div>

    <p v-if="isProvisional" class="notice provisional">
      ⚠️ 임시 채점 결과입니다. 이 케이스에는 검수된 기준 마스크가 없어 좌표 근사로 계산했습니다 —
      점수를 학습 판단 근거로 쓰지 마세요.
    </p>

    <!-- 판정 + 수치 -->
    <div class="verdict" :class="result.grade">
      <div class="verdict-head">
        <strong class="grade">{{ GRADE_LABEL[result.grade] ?? result.grade }}</strong>
        <p>{{ GRADE_DESC[result.grade] ?? '' }}</p>
      </div>
      <dl class="metrics">
        <div>
          <dt>Dice</dt>
          <dd class="metric-value">{{ result.dice }}</dd>
          <div class="track"><div class="fill" :style="{ width: ratio(result.dice) + '%' }"></div></div>
        </div>
        <div>
          <dt>IoU</dt>
          <dd class="metric-value">{{ result.iou }}</dd>
          <div class="track"><div class="fill" :style="{ width: ratio(result.iou) + '%' }"></div></div>
        </div>
        <div>
          <dt>위치 점수</dt>
          <dd class="metric-value">{{ result.location_score }}<small>/100</small></dd>
          <div class="track">
            <div class="fill" :style="{ width: ratio(result.location_score, 100) + '%' }"></div>
          </div>
        </div>
      </dl>
    </div>

    <!-- 오버레이 -->
    <div class="viewer-frame overlay-frame">
      <div class="viewer-bar">
        <label class="toggle">
          <input type="checkbox" v-model="showUser" />
          <i class="sw user"></i>
          내 ROI
        </label>
        <label class="toggle">
          <input type="checkbox" v-model="showAi" />
          <i class="sw ai"></i>
          기준 마스크
        </label>
        <span v-if="pixelMode" class="toggle static">
          <i class="sw both"></i>
          겹침
        </span>
        <span class="spacer"></span>
        <span class="dim">기준 마스크 대조</span>
      </div>

      <div class="stage" :style="{ aspectRatio }">
        <img v-if="baseImageUrl" :src="baseImageUrl" alt="의료영상" class="base" />
        <div v-else class="base placeholder"><span>영상 없음</span></div>

        <!-- 픽셀 합성 오버레이 -->
        <canvas v-if="pixelMode" ref="outCanvas" class="layer"></canvas>
        <!-- 폴백: 두 마스크를 반투명하게 겹쳐 표시 -->
        <template v-else>
          <img v-if="showUser && userMaskDataUrl" :src="userMaskDataUrl" class="layer tint-user" alt="사용자 ROI" />
          <img v-if="showAi && referenceMaskUrl" :src="referenceMaskUrl" class="layer tint-ai" alt="기준 마스크" />
        </template>
      </div>
    </div>

    <p v-if="overlayNote" class="muted note">{{ overlayNote }}</p>

    <!-- AI 예측은 참고 정보일 뿐 채점에 쓰이지 않는다 (api-spec v0.4) -->
    <div v-if="aiPrediction" class="ai-note">
      <strong>AI 예측 (참고)</strong>
      <span class="muted">
        model {{ aiPrediction.model_version }}
        <template v-if="aiPrediction.dice_vs_reference !== null">
          · 기준 마스크와의 Dice {{ aiPrediction.dice_vs_reference }}
        </template>
        <template v-if="aiPrediction.representative_slice_dice != null">
          (이 slice {{ aiPrediction.representative_slice_dice }})
        </template>
      </span>
      <span v-if="aiPrediction.detected === false" class="missed">
        이 케이스는 <strong>모델이 병변을 찾지 못했습니다.</strong>
        모델도 놓치는 경우가 있으며, 채점 기준은 전문가 기준 마스크입니다.
      </span>
      <span class="muted">이 값은 채점에 사용되지 않았습니다.</span>
    </div>
  </section>
</template>

<style scoped>
.provisional {
  margin-bottom: var(--sp-4);
}

.missed {
  flex-basis: 100%;
  padding: 8px 10px;
  border-radius: var(--r-sm);
  background: var(--partial-bg);
  border: 1px solid var(--partial-line);
  color: var(--partial-ink);
  font-size: 12.5px;
  line-height: 1.55;
}

.ai-note {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--sp-2);
  margin-top: var(--sp-3);
  padding: 10px 12px;
  border: 1px dashed var(--line-strong);
  border-radius: var(--r-sm);
  max-width: 560px;
  font-size: 13px;
}

.verdict {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--sp-5);
  padding: var(--sp-4);
  margin-bottom: var(--sp-4);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--gray-25);
}

.verdict.match {
  background: var(--match-bg);
  border-color: var(--match-line);
}

.verdict.partial_match {
  background: var(--partial-bg);
  border-color: var(--partial-line);
}

.verdict.mismatch {
  background: var(--mismatch-bg);
  border-color: var(--mismatch-line);
}

.verdict-head {
  flex: 1 1 200px;
}

.grade {
  display: block;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.03em;
  margin-bottom: 2px;
}

.verdict.match .grade {
  color: var(--match-ink);
}

.verdict.partial_match .grade {
  color: var(--partial-ink);
}

.verdict.mismatch .grade {
  color: var(--mismatch-ink);
}

.verdict-head p {
  font-size: 13px;
  color: var(--ink-secondary);
  line-height: 1.5;
}

.metrics {
  display: flex;
  gap: var(--sp-5);
  margin: 0;
  flex: 0 0 auto;
}

.metrics > div {
  min-width: 74px;
}

dt {
  color: var(--ink-muted);
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0;
}

dd {
  margin: 1px 0 5px;
  font-size: 19px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

dd small {
  font-size: 11.5px;
  font-weight: 500;
  color: var(--ink-muted);
  margin-left: 1px;
}

.track {
  height: 4px;
  border-radius: var(--r-full);
  background: rgba(21, 26, 35, 0.1);
  overflow: hidden;
}

/* 막대는 색 자체가 정보이므로 텍스트 잉크가 아닌 검증된 --mark-* 색을 쓴다 */
.fill {
  height: 100%;
  border-radius: 0 2px 2px 0;
  background: var(--mark-match);
}

.verdict.partial_match .fill {
  background: var(--mark-partial);
}

.verdict.mismatch .fill {
  background: var(--mark-mismatch);
}

.overlay-frame {
  max-width: 560px;
}

.toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 12.5px;
}

.toggle.static {
  cursor: default;
  color: var(--viewer-ink-dim);
}

.sw {
  width: 11px;
  height: 11px;
  border-radius: 3px;
  display: inline-block;
}

.sw.user {
  background: var(--roi-user);
}

.sw.ai {
  background: var(--roi-reference);
}

.sw.both {
  background: var(--roi-overlap);
}

.stage {
  position: relative;
  width: 100%;
  background: var(--viewer-bg);
}

.base {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.base.placeholder {
  display: grid;
  place-items: center;
  color: var(--viewer-ink-dim);
  font-size: 13px;
}

.layer {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}

.tint-user {
  opacity: 0.5;
  filter: hue-rotate(200deg) saturate(3);
}

.tint-ai {
  opacity: 0.5;
}

.note {
  margin-top: var(--sp-3);
  max-width: 560px;
}

@media (max-width: 560px) {
  .metrics {
    gap: var(--sp-4);
  }
}
</style>
