<script setup>
/**
 * 오답 상세 (시안 10) — **다시 풀기 전에 무엇을 놓쳤는지 먼저 보는 화면.**
 *
 * 왜 만들었나
 * ----------
 * 해설은 **제출 직후에만** 볼 수 있었다. 복습노트에서 케이스를 누르면 바로 판독
 * 화면으로 갔고, 해설을 다시 보려면 또 제출해야 했다 — 틀린 것을 복습하러 와서
 * 무엇을 틀렸는지 못 보고 다시 칠하는 구조였다. 학습 루프의 빠진 고리다.
 *
 * 시안과 다르게 한 것
 * -----------------
 * 시안 10 의 "내 답안 vs 정답"은 **질환명을 고르는 퀴즈**다(기관지염 vs 폐렴).
 * 우리는 영역을 칠하는 방식이라 그 자리에 넣을 "답안"이 없다 —
 * 대신 **내 일치도와 기준 영역**을 같은 자리에 놓는다. 구조는 시안 그대로다.
 *
 * **사용자가 칠한 마스크는 저장하지 않는다.** 그래서 여기서는 기준 영역만 겹쳐
 * 보여주고, 그 사실을 화면에 밝힌다 — 없는 것을 있는 것처럼 그리지 않는다.
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { getWrongNoteDetail } from '../api/endpoints'
import { bodyPartLabel, diseaseLabel, gradeLabel } from '../labels'
import ExplanationPanel from '../components/ExplanationPanel.vue'

const route = useRoute()
const caseId = route.params.caseId

const data = ref(null)
const loading = ref(true)
const errorMessage = ref('')

onMounted(async () => {
  try {
    data.value = await getWrongNoteDetail(caseId)
  } catch (e) {
    errorMessage.value =
      e.status === 404
        ? '아직 제출한 적이 없는 케이스입니다. 먼저 한 번 풀어야 복습할 내용이 생깁니다.'
        : e.message || '불러오지 못했습니다.'
  } finally {
    loading.value = false
  }
})

const latest = computed(() => data.value?.latest ?? null)
const aspectRatio = computed(() => {
  const m = data.value?.image_meta ?? {}
  return `${m.width || 512} / ${m.height || 512}`
})

function percent(value) {
  return value == null ? null : Math.round(value * 100)
}
</script>

<template>
  <section class="detail">
    <header class="head">
      <RouterLink to="/wrong-notes" class="back">‹ 복습노트</RouterLink>
      <div>
        <h1>오답 상세</h1>
        <p class="lead">다시 풀기 전에 기준 영역과 해설을 확인하세요.</p>
      </div>
    </header>

    <p v-if="loading" class="muted loading">불러오는 중…</p>
    <p v-else-if="errorMessage" class="notice">{{ errorMessage }}</p>

    <template v-else-if="data">
      <div class="cols">
        <!-- 왼쪽: 영상 + 기준 영역 (시안 10 의 왼쪽 칸) -->
        <div class="col-left">
          <div class="viewer-frame">
            <div class="viewer-bar">
              <span class="dim">
                {{ bodyPartLabel(data.body_part) }}
                <span class="dot">·</span>
                {{ diseaseLabel(data.disease) }}
              </span>
              <span class="spacer"></span>
              <span class="legend">
                <i class="sw ref"></i>
                기준 영역
              </span>
            </div>

            <div class="stage" :style="{ aspectRatio }">
              <img v-if="data.image_url" :src="data.image_url" alt="의료영상" class="base" />
              <div v-else class="base placeholder"><span>영상 없음</span></div>
              <div
                v-if="data.reference_mask_url"
                class="layer"
                :style="{ '--mask-src': `url(${data.reference_mask_url})` }"
                role="img"
                aria-label="전문가가 검수한 기준 영역"
              ></div>
            </div>
          </div>

          <!-- **없는 것을 있는 것처럼 그리지 않는다.** -->
          <p v-if="data.user_mask_kept === false" class="muted note">
            표시된 영역은 전문가가 검수한 <strong>기준 영역</strong>입니다.
            내가 칠했던 영역은 서버에 저장하지 않아 여기서는 다시 보여줄 수 없습니다.
          </p>
        </div>

        <!-- 오른쪽: 내 결과 + 해설 (시안 10 의 오른쪽 칸) -->
        <div class="col-right">
          <div class="card result-card">
            <h2 class="card-title">내 결과</h2>

            <div class="verdict-row">
              <span class="grade-pill" :class="latest.grade">{{ gradeLabel(latest.grade) }}</span>
              <span v-if="latest.dice != null" class="headline">
                <span class="tnum headline-num">{{ percent(latest.dice) }}</span
                ><span class="headline-unit">%</span>
                <span class="headline-label">기준과 일치</span>
              </span>
            </div>

            <dl class="metrics">
              <div>
                <dt>시도</dt>
                <dd class="tnum">{{ data.attempts }}회</dd>
              </div>
              <div v-if="data.best_dice != null">
                <dt>최고 일치도</dt>
                <dd class="tnum">{{ percent(data.best_dice) }}%</dd>
              </div>
              <div v-if="latest.location_score != null">
                <dt>위치 점수</dt>
                <dd class="tnum">{{ latest.location_score }}</dd>
              </div>
            </dl>

            <p class="muted note">
              여기 숫자는 <strong>내가 표시한 영역과 기준 마스크의 일치도</strong>입니다.
              케이스의 의학적 난이도를 뜻하지 않습니다.
            </p>
          </div>

          <ExplanationPanel v-if="data.explanation" :explanation="data.explanation" />
        </div>
      </div>

      <!-- 시안 10 의 하단 버튼 두 개 -->
      <div class="actions">
        <RouterLink class="btn primary lg" :to="{ name: 'retry', params: { caseId } }">
          다시 풀기
        </RouterLink>
        <RouterLink class="btn lg" to="/wrong-notes">목록으로</RouterLink>
      </div>
    </template>
  </section>
</template>

<style scoped>
.detail {
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
}

.head {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-4);
}
.back {
  display: inline-flex;
  align-items: center;
  min-height: 38px;
  padding: 0 var(--sp-3);
  border: 1px solid var(--line);
  border-radius: var(--r-sm);
  color: var(--ink-secondary);
  font-size: 13px;
  text-decoration: none;
  flex: 0 0 auto;
}
.back:hover {
  border-color: var(--brand-300);
  color: var(--brand-600);
}
.head h1 {
  margin: 0 0 2px;
  font-size: 26px;
  color: var(--navy-700);
}

/* 시안 10 의 좌우 2단 */
.cols {
  display: grid;
  grid-template-columns: minmax(0, 5fr) minmax(0, 6fr);
  gap: var(--sp-5);
  align-items: start;
}
.col-left,
.col-right {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  min-width: 0;
}

/* 해설은 길고(1,300px 넘는다) 영상은 짧다. 붙여 두지 않으면 **해설을 읽는 내내
   기준 영역이 화면 밖에 있다** — 무엇을 놓쳤는지 보려고 들어온 화면인데 정작
   그 그림을 못 본 채로 글만 읽게 된다. 스크롤을 따라오게 붙인다. */
@media (min-width: 861px) {
  .col-left {
    position: sticky;
    top: 76px;
  }
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
  object-fit: contain;
  /* 기준 마스크는 **흰 픽셀 + 투명 배경** PNG 다. 그대로 얹으면 흰 덩어리라
     영상의 밝은 부분과 구분되지 않는다 — 결과 화면 레전드와 같은 초록으로 물들인다.
     (마스크 자체를 고치는 게 아니라 보여주는 색만 바꾼다) */
  opacity: 0.55;
  background: var(--roi-reference);
  -webkit-mask-image: var(--mask-src);
  mask-image: var(--mask-src);
  -webkit-mask-size: contain;
  mask-size: contain;
  -webkit-mask-repeat: no-repeat;
  mask-repeat: no-repeat;
  -webkit-mask-position: center;
  mask-position: center;
}

.legend {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--viewer-ink);
}
.sw {
  display: inline-block;
  width: 11px;
  height: 11px;
  border-radius: 3px;
}
.sw.ref {
  background: var(--roi-reference);
}

.verdict-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  flex-wrap: wrap;
  margin: var(--sp-3) 0;
}
/* 결과 화면과 같은 알약 모양 — 두 화면이 같은 판정을 다르게 그리면 혼란스럽다 */
.grade-pill {
  display: inline-block;
  padding: 7px 20px;
  border-radius: var(--r-full);
  font-size: 18px;
  font-weight: 700;
  color: #fff;
  background: var(--gray-600);
}
.grade-pill.match {
  background: var(--match-ink);
}
.grade-pill.partial_match {
  background: var(--partial-ink);
}
.grade-pill.mismatch {
  background: var(--mismatch-ink);
}

.headline {
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.headline-num {
  font-size: 32px;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--navy-700);
}
.headline-unit {
  font-size: 16px;
  font-weight: 700;
  color: var(--ink-secondary);
}
.headline-label {
  margin-left: var(--sp-2);
  font-size: 12px;
  color: var(--ink-muted);
}

.metrics {
  display: flex;
  gap: var(--sp-6);
  margin: 0;
  padding-top: var(--sp-3);
  border-top: 1px solid var(--line);
  flex-wrap: wrap;
}
.metrics dt {
  font-size: 12px;
  color: var(--ink-muted);
}
.metrics dd {
  margin: 2px 0 0;
  font-size: 17px;
  font-weight: 700;
  color: var(--navy-700);
}

.note {
  margin: var(--sp-3) 0 0;
  font-size: 12.5px;
  line-height: 1.7;
}

.actions {
  display: flex;
  gap: var(--sp-3);
  flex-wrap: wrap;
}
.actions .btn {
  min-width: 180px;
  justify-content: center;
}

.loading {
  padding: var(--sp-8) 0;
}

@media (max-width: 980px) {
  .cols {
    grid-template-columns: 1fr;
  }
}
</style>
