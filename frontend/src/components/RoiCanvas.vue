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
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = defineProps({
  imageUrl: { type: String, default: null },
  /**
   * 배경 영상이 바뀔 때 그린 ROI 를 지울지.
   *
   * 화면 5(업로드 분석)는 **다른 영상으로 교체**하는 것이라 이전 입력을 지워야 한다(true).
   * 화면 2(판독 훈련)는 같은 케이스의 **다른 slice 를 넘겨보는 것**이라 지우면 안 된다 —
   * 범위를 확인하러 옆 slice 에 다녀왔더니 칠하던 게 사라지면 작업을 다시 해야 한다.
   */
  clearOnImageChange: { type: Boolean, default: true },
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

/** 화면에는 사람이 읽을 문장만 두고, 진단에 필요한 주소는 콘솔로 보낸다. */
function onImageError() {
  imageBroken.value = true
  console.warn('[RoiCanvas] 영상을 불러오지 못했습니다:', props.imageUrl)
}

const hasInput = computed(() => points.value.length > 0 || strokeCount.value > 0)

// 캔버스를 스크린리더가 무엇이라고 읽을지. 화면에 보이는 상태(잠김/표시 여부)를 그대로 옮긴다.
const canvasLabel = computed(() => {
  const what = '의료영상 위에 이상 부위를 표시하는 영역'
  if (props.disabled) return `${what} (입력 잠김)`
  return hasInput.value
    ? `${what} — 표시함 (스트로크 ${strokeCount.value}개)`
    : `${what} — 아직 표시하지 않음`
})
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
  history.value = []
  historyIndex.value = -1
  notify()
  pushHistory() // 빈 상태도 되돌아갈 수 있는 지점이다
}

onMounted(() => {
  if (!props.tools.includes(tool.value)) tool.value = props.tools[0]
  initCanvases()
})
// 캔버스 버퍼 크기가 달라지면 반드시 다시 잡아야 한다 (입력도 함께 비워진다).
watch(() => [props.width, props.height], initCanvases)

// 배경 영상만 바뀐 경우. 배경은 <img> 로 그리므로 캔버스를 건드릴 필요가 없다 —
// clearOnImageChange 가 true 일 때만(업로드 교체) 입력을 비운다.
watch(
  () => props.imageUrl,
  () => {
    if (props.clearOnImageChange) initCanvases()
  },
)

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
    pushHistory()
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
  // **획 단위로 되돌린다.** 픽셀 단위로 쌓으면 되돌리기가 한 번에
  // 눈에 띄는 변화를 만들지 못해 쓸모가 없다.
  pushHistory()
}

function clear() {
  if (!viewCtx) return
  viewCtx.clearRect(0, 0, viewCanvas.value.width, viewCanvas.value.height)
  maskCtx.clearRect(0, 0, maskCanvas.width, maskCanvas.height)
  points.value = []
  strokeCount.value = 0
  notify()
  pushHistory()
}

/* ---------------------------------------------------------------------
   되돌리기 / 다시하기
   ---------------------------------------------------------------------
   **여기 없던 것 중 가장 아쉬웠던 기능.** 실수를 되돌릴 방법이
   "전체 지우기" 뿐이라, 마지막 한 획이 틀리면 처음부터 다시 칠해야 했다.
   판독 훈련에서 그건 학습이 아니라 노동이다.

   스냅샷은 **마스크 PNG 문자열**로 보관한다.
   `ImageData` 로 들고 있으면 512×512 한 장이 1MB 라 20단계면 20MB 다.
   마스크는 대부분이 투명이라 PNG 로는 몇 KB 로 줄어든다.
   화면용 캔버스는 마스크에서 색만 입혀 되살릴 수 있으므로 따로 저장하지 않는다.
--------------------------------------------------------------------- */
const HISTORY_LIMIT = 25
const history = ref([])
const historyIndex = ref(-1)
const canUndo = computed(() => historyIndex.value > 0)
const canRedo = computed(() => historyIndex.value < history.value.length - 1)

function pushHistory() {
  if (!maskCanvas) return
  // 되돌린 뒤 새로 그리면 그 앞의 "다시하기" 가지는 버린다 (일반적인 편집기 동작)
  history.value = history.value.slice(0, historyIndex.value + 1)
  history.value.push({
    mask: maskCanvas.toDataURL('image/png'),
    points: points.value.map(([x, y]) => [x, y]),
    strokeCount: strokeCount.value,
  })
  if (history.value.length > HISTORY_LIMIT) history.value.shift()
  historyIndex.value = history.value.length - 1
}

function repaintViewFromMask() {
  const w = viewCanvas.value.width
  const h = viewCanvas.value.height
  viewCtx.clearRect(0, 0, w, h)
  viewCtx.save()
  viewCtx.drawImage(maskCanvas, 0, 0)
  // 마스크(흰색)를 화면용 반투명 파랑으로 물들인다
  viewCtx.globalCompositeOperation = 'source-in'
  viewCtx.fillStyle = 'rgba(47, 98, 232, 0.55)'
  viewCtx.fillRect(0, 0, w, h)
  viewCtx.restore()
}

async function applySnapshot(snapshot) {
  points.value = snapshot.points.map(([x, y]) => [x, y])
  strokeCount.value = snapshot.strokeCount
  await new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      maskCtx.clearRect(0, 0, maskCanvas.width, maskCanvas.height)
      maskCtx.drawImage(img, 0, 0)
      repaintViewFromMask()
      resolve()
    }
    // 스냅샷을 못 읽어도 **입력을 잃지는 않게** 한다 — 현재 화면을 그대로 둔다
    img.onerror = resolve
    img.src = snapshot.mask
  })
  notify()
}

async function undo() {
  if (!canUndo.value) return
  historyIndex.value -= 1
  await applySnapshot(history.value[historyIndex.value])
}

async function redo() {
  if (!canRedo.value) return
  historyIndex.value += 1
  await applySnapshot(history.value[historyIndex.value])
}

function onKeydown(event) {
  if (props.disabled) return
  const mod = event.ctrlKey || event.metaKey
  if (!mod || event.key.toLowerCase() !== 'z') return
  event.preventDefault()
  if (event.shiftKey) redo()
  else undo()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

/** 부모(화면 2·5)가 제출 직전에 호출한다. */
defineExpose({
  clear,
  undo,
  redo,
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

        <!-- **획 단위로 되돌린다.** 예전에는 실수를 되돌릴 방법이 "전체 지우기"
             뿐이라, 마지막 한 획이 틀리면 처음부터 다시 칠해야 했다. -->
        <div class="history">
          <button
            class="icon"
            :disabled="disabled || !canUndo"
            title="되돌리기 (Ctrl+Z)"
            aria-label="되돌리기"
            @click="undo"
          >
            ↺
          </button>
          <button
            class="icon"
            :disabled="disabled || !canRedo"
            title="다시하기 (Ctrl+Shift+Z)"
            aria-label="다시하기"
            @click="redo"
          >
            ↻
          </button>
        </div>

        <button :disabled="disabled || !hasInput" @click="clear">전체 지우기</button>
      </div>

      <!-- 영상 + ROI 오버레이 -->
      <div class="stage" :style="{ aspectRatio }">
        <img
          v-if="imageUrl"
          :src="imageUrl"
          alt="의료영상"
          class="base"
          @error="onImageError"
          @load="imageBroken = false"
        />
        <div v-else class="base placeholder">
          <span>영상 없음</span>
        </div>
        <!--
          캔버스 내용은 픽셀뿐이라 대체 설명이 없으면 스크린리더에 아무것도 전달되지 않는다
          (요소 자체가 조용히 건너뛰어진다). 무엇을 위한 영역이고 지금 어떤 상태인지를
          이름으로 남긴다.

          다만 **이것으로 ROI 그리기가 접근 가능해지는 것은 아니다.** 포인터로 자유곡선을
          그리는 입력을 키보드·스크린리더로 대체하려면 별도 입력 수단이 필요하다.
          지금은 "여기에 무엇이 있는지 알 수 있다"까지만 한다.
        -->
        <canvas
          ref="viewCanvas"
          class="overlay"
          :class="[tool, { locked: disabled }]"
          role="img"
          :aria-label="canvasLabel"
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

    <!-- **서명 URL 을 화면에 그대로 뿌리지 않는다.** 사용자가 할 수 있는 일도 없고,
         서명·만료 파라미터까지 노출된다. 개발자용 정보는 콘솔로 보낸다. -->
    <p v-if="imageUrl && imageBroken" class="muted note">
      영상을 불러오지 못했습니다. 표시(ROI) 입력과 제출은 그대로 동작합니다.
    </p>
  </div>
</template>

<style scoped>
.roi {
  /* **부모가 정한다.** 560px 이 여기 박혀 있어서, 화면이 아무리 넓어도
     판독 영상이 커지지 않았다 — 1440px 화면에서 영상이 절반도 못 썼다.
     의료영상 학습에서 영상 크기는 기능이다. 기본값은 예전 그대로라
     이 컴포넌트를 쓰는 다른 화면(결과 비교)은 영향을 받지 않는다. */
  max-width: var(--roi-max-width, 560px);
  margin-inline: auto;
}

.tools,
.history {
  display: flex;
  gap: 4px;
}

.viewer-bar .icon {
  /* 반응형 점검이 30×30 을 "누르기 힘든 크기"로 잡았다 (권장 44px).
     아이콘 글자는 그대로 두고 **누를 수 있는 면적만** 넓힌다. */
  min-width: 34px;
  min-height: 34px;
  padding: 4px 9px;
  font-size: 15px;
  line-height: 1.2;
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
