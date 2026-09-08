<script setup>
/**
 * ROI 입력 위젯 — 화면 2(판독 훈련)와 화면 5(사용자 영상 분석)가 함께 쓴다.
 *
 * 캔버스를 두 장 쓴다:
 *  - 화면용(view) : 반투명 파란색으로 사용자에게 보여주는 오버레이
 *  - 제출용(mask) : 같은 좌표에 불투명 흰색으로 그린 뒤 toDataURL 로 mask_png_base64 생성
 * 둘 다 원본 해상도(width/height props)로 잡아두면 화면 크기와 무관하게
 * 원본 픽셀 좌표계 기준 마스크·좌표가 백엔드로 넘어간다.
 *
 * 도구 막대는 영상 위(다크 바)에 붙인다 — 판독 중 시선이 영상을 벗어나지 않게.
 */
import { computed, onMounted, ref, watch } from 'vue'

const props = defineProps({
  imageUrl: { type: String, default: null },
  width: { type: Number, default: 512 },
  height: { type: Number, default: 512 },
  disabled: { type: Boolean, default: false },
  // 제공할 도구. 판독훈련(화면 2)은 브러시+지우개만 쓴다 — 단일 클릭은 면적이 거의 없어
  // Dice 기반 채점에서 낮은 점수가 나오므로, 별도 위치 채점이 생기기 전까지 제외한다.
  tools: { type: Array, default: () => ['brush', 'eraser'] },
})
const emit = defineEmits(['change'])

const viewCanvas = ref(null)
let viewCtx = null
let maskCanvas = null
let maskCtx = null

const tool = ref('brush') // 'brush' | 'point' | 'eraser'
const brushSize = ref(24)
const points = ref([]) // api-spec.md 2-3 roi.points — 원본 픽셀 좌표
const strokeCount = ref(0)
const imageBroken = ref(false)

const hasInput = computed(() => points.value.length > 0 || strokeCount.value > 0)
// 뷰어 박스를 원본 비율과 똑같이 맞춘다. 그래야 letterbox 여백 없이
// 캔버스 좌표와 화면상의 이미지 픽셀이 1:1로 대응한다 (업로드 영상이 정사각형이 아닐 때 중요).
const aspectRatio = computed(() => `${props.width} / ${props.height}`)

const TOOL_LABELS = { brush: '브러시', point: '클릭', eraser: '지우개' }
const availableTools = computed(() =>
  props.tools.map((key) => ({ key, label: TOOL_LABELS[key] ?? key })),
)

function notify() {
  emit('change', { pointCount: points.value.length, strokeCount: strokeCount.value, hasInput: hasInput.value })
}

function initCanvases() {
  if (!viewCanvas.value) return
  viewCanvas.value.width = props.width
  viewCanvas.value.height = props.height
  viewCtx = viewCanvas.value.getContext('2d')

  maskCanvas = document.createElement('canvas')
  maskCanvas.width = props.width
  maskCanvas.height = props.height
  maskCtx = maskCanvas.getContext('2d')

  points.value = []
  strokeCount.value = 0
  notify()
}

onMounted(() => {
  if (!props.tools.includes(tool.value)) tool.value = props.tools[0]
  initCanvases()
})
// 이미지가 바뀌면(업로드 교체 등) 캔버스 크기를 다시 잡고 입력을 비운다.
watch(() => [props.width, props.height, props.imageUrl], initCanvases)

/** 화면 좌표 -> 원본 픽셀 좌표 */
function toImageCoords(event) {
  const rect = viewCanvas.value.getBoundingClientRect()
  return {
    x: Math.round(((event.clientX - rect.left) / rect.width) * viewCanvas.value.width),
    y: Math.round(((event.clientY - rect.top) / rect.height) * viewCanvas.value.height),
  }
}

const LAYERS = () => [
  { ctx: viewCtx, color: 'rgba(47, 98, 232, 0.55)' },
  { ctx: maskCtx, color: '#ffffff' },
]

function withLayer(fn) {
  for (const { ctx, color } of LAYERS()) {
    ctx.save()
    if (tool.value === 'eraser') ctx.globalCompositeOperation = 'destination-out'
    ctx.strokeStyle = color
    ctx.fillStyle = color
    ctx.lineWidth = brushSize.value
    ctx.lineCap = 'round'
    ctx.lineJoin = 'round'
    fn(ctx)
    ctx.restore()
  }
}

function drawDot(p) {
  withLayer((ctx) => {
    ctx.beginPath()
    ctx.arc(p.x, p.y, brushSize.value / 2, 0, Math.PI * 2)
    ctx.fill()
  })
}

function drawSegment(from, to) {
  withLayer((ctx) => {
    ctx.beginPath()
    ctx.moveTo(from.x, from.y)
    ctx.lineTo(to.x, to.y)
    ctx.stroke()
  })
}

/** 지우개로 지운 영역의 좌표는 points 에서도 빼준다 (마스크와 points 가 어긋나지 않게). */
function erasePointsNear(p) {
  const r = brushSize.value / 2
  points.value = points.value.filter(([x, y]) => Math.hypot(x - p.x, y - p.y) > r)
}

let drawing = false
let last = null

function onPointerDown(event) {
  if (props.disabled || !viewCtx) return
  const p = toImageCoords(event)

  if (tool.value === 'point') {
    // 클릭 도구: 점 하나 = points 배열에 좌표 하나 추가
    drawDot(p)
    points.value.push([p.x, p.y])
    notify()
    return
  }

  drawing = true
  last = p
  viewCanvas.value.setPointerCapture(event.pointerId)
  drawDot(p)
  if (tool.value === 'brush') {
    strokeCount.value += 1
    points.value.push([p.x, p.y])
  } else {
    erasePointsNear(p)
  }
  notify()
}

function onPointerMove(event) {
  if (!drawing) return
  const p = toImageCoords(event)
  drawSegment(last, p)
  last = p
  if (tool.value === 'brush') {
    // 궤적도 points 에 남긴다 (너무 촘촘하지 않게 4px 이상 이동했을 때만)
    const [lx, ly] = points.value[points.value.length - 1] ?? [0, 0]
    if (Math.abs(p.x - lx) + Math.abs(p.y - ly) >= 4) points.value.push([p.x, p.y])
  } else {
    erasePointsNear(p)
  }
  notify()
}

function onPointerUp(event) {
  if (!drawing) return
  drawing = false
  last = null
  viewCanvas.value.releasePointerCapture?.(event.pointerId)
}

function clear() {
  if (!viewCtx) return
  viewCtx.clearRect(0, 0, viewCanvas.value.width, viewCanvas.value.height)
  maskCtx.clearRect(0, 0, maskCanvas.width, maskCanvas.height)
  points.value = []
  strokeCount.value = 0
  notify()
}

/** 부모(화면 2·5)가 제출 직전에 호출한다. */
defineExpose({
  clear,
  getPoints: () => points.value.map(([x, y]) => [x, y]),
  getMaskDataUrl: () => maskCanvas?.toDataURL('image/png') ?? null,
  getMaskBase64: () => maskCanvas?.toDataURL('image/png').split(',')[1] ?? null,
})
</script>

<template>
  <div class="roi">
    <div class="viewer-frame">
      <!-- 도구 막대 -->
      <div class="viewer-bar">
        <div class="tools">
          <button
            v-for="t in availableTools"
            :key="t.key"
            :class="{ active: tool === t.key }"
            :disabled="disabled"
            @click="tool = t.key"
          >
            {{ t.label }}
          </button>
        </div>

        <label class="size">
          <span class="dim">굵기</span>
          <input type="range" min="4" max="60" v-model.number="brushSize" :disabled="disabled" />
          <span class="dim val">{{ brushSize }}</span>
        </label>

        <span class="spacer"></span>

        <button :disabled="disabled || !hasInput" @click="clear">전체 지우기</button>
      </div>

      <!-- 영상 + ROI 오버레이 -->
      <div class="stage" :style="{ aspectRatio }">
        <img
          v-if="imageUrl"
          :src="imageUrl"
          alt="의료영상"
          class="base"
          @error="imageBroken = true"
          @load="imageBroken = false"
        />
        <div v-else class="base placeholder">
          <span>영상 없음</span>
        </div>
        <canvas
          ref="viewCanvas"
          class="overlay"
          :class="[tool, { locked: disabled }]"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerUp"
        ></canvas>

        <span v-if="disabled" class="lock-tag">입력 잠김</span>
      </div>

      <!-- 상태 줄 -->
      <div class="viewer-bar foot">
        <span class="dim">{{ width }} × {{ height }}</span>
        <span class="spacer"></span>
        <span class="dim tnum">좌표 {{ points.length }} · 스트로크 {{ strokeCount }}</span>
      </div>
    </div>

    <p v-if="imageUrl && imageBroken" class="muted note">
      {{ imageUrl }} 이미지를 찾을 수 없습니다. 이미지가 없어도 ROI 입력·제출은 그대로 동작합니다.
    </p>
  </div>
</template>

<style scoped>
.roi {
  max-width: 560px;
}

.tools {
  display: flex;
  gap: 4px;
}

.size {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.size input[type='range'] {
  width: 88px;
}

.size .val {
  width: 18px;
  text-align: right;
  font-variant-numeric: tabular-nums;
}

.viewer-bar.foot {
  border-bottom: 0;
  border-top: 1px solid var(--viewer-line);
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

.overlay {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  touch-action: none;
}

.overlay.brush,
.overlay.eraser {
  cursor: crosshair;
}

.overlay.point {
  cursor: pointer;
}

.overlay.locked {
  pointer-events: none;
}

.lock-tag {
  position: absolute;
  top: 10px;
  left: 10px;
  padding: 3px 9px;
  border-radius: var(--r-full);
  background: rgba(13, 17, 23, 0.75);
  border: 1px solid rgba(255, 255, 255, 0.16);
  color: #e7ecf3;
  font-size: 11.5px;
  font-weight: 600;
  backdrop-filter: blur(4px);
}

.note {
  margin-top: var(--sp-2);
}
</style>
