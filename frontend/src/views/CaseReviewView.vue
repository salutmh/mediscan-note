<script setup>
/**
 * 케이스 후보 **기술 검수** 화면 (운영자 전용).
 *
 * ==========================================================================
 * **여기서 하는 것은 기술 검수뿐이다.**
 * ==========================================================================
 * "export 파이프라인이 제대로 돌았는가"를 본다. 구체적으로는 마스크 정렬, 메타데이터와
 * 그림의 일치, ROI 종류, 화질이다. 판단 기준은 `docs/CASE_REVIEW_CHECKLIST.md` 2절.
 *
 * `TECH_PASS` 는 **의학적으로 옳다거나 서비스에 올려도 된다는 뜻이 아니다.**
 * 그래서 상태를 셋으로 나눠 화면에도 항상 셋 다 보여준다:
 *   기술 검수 / 전문가 검수 / 활성화
 *
 * **이 화면은 의료 소견을 만들지 않는다.** 표시하는 값은 전부 export 단계에서 계산된
 * 것을 그대로 옮긴 것이고, 메모도 기술 메모지 소견이 아니다.
 *
 * AI 예측이 있으면 GT 와 **완전히 다른 색·블록**으로 분리해 보여준다 —
 * "AI 가 못 찾았으니 GT 가 틀렸다"로 읽히면 안 된다 (VS-SEG-204 가 그 반례다).
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import { ApiError, fetchObjectUrl } from '../api/client'
import { listReviewCandidates, reviewSheetPath, setTechnicalReview } from '../api/endpoints'

const TECH = {
  UNREVIEWED: 'unreviewed',
  PASS: 'tech_pass',
  HOLD: 'hold',
  REJECT: 'reject_tech',
}
const TECH_LABEL = {
  [TECH.UNREVIEWED]: '미검수',
  [TECH.PASS]: 'TECH PASS',
  [TECH.HOLD]: 'HOLD',
  [TECH.REJECT]: 'REJECT',
}
const EXPERT_LABEL = {
  pending: '전문가 검수 대기',
  in_review: '전문가 검수 중',
  approved: '전문가 승인',
  rejected: '전문가 반려',
}
const ACTIVATION_LABEL = {
  candidate: '후보 (미등록)',
  inactive_ready: '등록됨 · 비활성',
  active: '활성',
}

const loading = ref(true)
const loadError = ref('')
const candidates = ref([])
// **서버가 준 스냅샷을 그대로 쓰지 않는다.** 판단할 때마다 헤더가 즉시 따라가야 하는데,
// 스냅샷은 새로고침 전까지 멈춰 있어 "24건 중 24건 미검수"가 계속 보인다.
// 목록에서 직접 센다 — 세는 규칙은 서버(review_store.counts)와 같다.
const serverCounts = ref(null)
const notice = ref('')
const roots = ref(null)
const filter = ref('all')
const cursor = ref(0)
const savingId = ref(null)
const savedId = ref(null)
const lightbox = ref(false)

// case_id -> objectURL. 화면을 떠날 때 전부 해제한다.
const sheetUrls = ref({})
const sheetErrors = ref({})

const filtered = computed(() => {
  const rows = candidates.value
  if (filter.value === 'all') return rows
  return rows.filter((c) => c.review.technical_review_status === filter.value)
})

const current = computed(() => filtered.value[cursor.value] ?? null)

const counts = computed(() => {
  const rows = candidates.value
  if (!rows.length) return serverCounts.value
  return {
    total: rows.length,
    technical: {
      unreviewed: countOf(TECH.UNREVIEWED),
      tech_pass: countOf(TECH.PASS),
      hold: countOf(TECH.HOLD),
      reject_tech: countOf(TECH.REJECT),
    },
    // 기술 통과했지만 전문가 검수가 남은 수. 이 값이 0 이 아니면 활성화하면 안 된다.
    awaiting_expert_review: rows.filter(
      (c) =>
        c.review.technical_review_status === TECH.PASS &&
        c.review.expert_review_status === 'pending',
    ).length,
  }
})

const filterOptions = computed(() => [
  { key: 'all', label: '전체', n: candidates.value.length },
  { key: TECH.UNREVIEWED, label: '미검수', n: countOf(TECH.UNREVIEWED) },
  { key: TECH.PASS, label: 'PASS', n: countOf(TECH.PASS) },
  { key: TECH.HOLD, label: 'HOLD', n: countOf(TECH.HOLD) },
  { key: TECH.REJECT, label: 'REJECT', n: countOf(TECH.REJECT) },
])

function countOf(status) {
  return candidates.value.filter((c) => c.review.technical_review_status === status).length
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const data = await listReviewCandidates()
    candidates.value = data.candidates
    serverCounts.value = data.counts
    notice.value = data.notice
    roots.value = data.roots
    cursor.value = 0
    loadSheets()
  } catch (e) {
    loadError.value = e instanceof ApiError ? e.message : '후보 목록을 불러오지 못했습니다.'
  } finally {
    loading.value = false
  }
}

/** 검수 시트는 인증 뒤에 있어 blob 으로 받아야 한다. 실패해도 카드는 그대로 보인다. */
async function loadSheets() {
  for (const c of candidates.value) {
    if (!c.sheet_available || sheetUrls.value[c.case_id]) continue
    try {
      sheetUrls.value = { ...sheetUrls.value, [c.case_id]: await fetchObjectUrl(reviewSheetPath(c.case_id)) }
    } catch {
      sheetErrors.value = { ...sheetErrors.value, [c.case_id]: true }
    }
  }
}

function releaseSheets() {
  Object.values(sheetUrls.value).forEach((url) => URL.revokeObjectURL(url))
  sheetUrls.value = {}
}

async function decide(caseId, status) {
  const target = candidates.value.find((c) => c.case_id === caseId)
  if (!target) return
  savingId.value = caseId
  try {
    const entry = await setTechnicalReview(caseId, {
      technical_review_status: status,
      note: target.review.note || '',
    })
    // 서버가 돌려준 값을 그대로 쓴다 (전문가·활성화 상태를 화면에서 만들어내지 않는다)
    target.review = entry
    savedId.value = caseId
    setTimeout(() => {
      if (savedId.value === caseId) savedId.value = null
    }, 1500)
  } catch (e) {
    loadError.value = e instanceof ApiError ? e.message : '검수 결과를 저장하지 못했습니다.'
  } finally {
    savingId.value = null
  }
}

async function saveNote(caseId) {
  const target = candidates.value.find((c) => c.case_id === caseId)
  if (!target) return
  await decide(caseId, target.review.technical_review_status)
}

function move(delta) {
  const n = filtered.value.length
  if (!n) return
  cursor.value = (cursor.value + delta + n) % n
  document
    .querySelector(`[data-case="${filtered.value[cursor.value].case_id}"]`)
    ?.scrollIntoView({ block: 'center', behavior: 'smooth' })
}

function onKey(event) {
  if (['INPUT', 'TEXTAREA'].includes(event.target?.tagName)) return
  if (lightbox.value && event.key === 'Escape') {
    lightbox.value = false
    return
  }
  const key = event.key.toLowerCase()
  if (key === 'arrowright' || key === 'j') return move(1)
  if (key === 'arrowleft' || key === 'k') return move(-1)
  if (!current.value) return
  if (key === 'p') return decide(current.value.case_id, TECH.PASS)
  if (key === 'h') return decide(current.value.case_id, TECH.HOLD)
  if (key === 'r') return decide(current.value.case_id, TECH.REJECT)
  if (key === 'u') return decide(current.value.case_id, TECH.UNREVIEWED)
  if (key === 'enter') lightbox.value = true
}

function setFilter(key) {
  filter.value = key
  cursor.value = 0
}

onMounted(() => {
  load()
  window.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKey)
  releaseSheets()
})
</script>

<template>
  <section class="page">
    <header class="head">
      <div>
        <h1>케이스 후보 기술 검수</h1>
        <p class="muted">
          export 파이프라인이 제대로 돌았는지 확인합니다.
          판단 기준은 <code>docs/CASE_REVIEW_CHECKLIST.md</code> 2절입니다.
        </p>
      </div>
      <button class="btn sm" :disabled="loading" @click="load">새로고침</button>
    </header>

    <!-- 서버가 내려준 문구를 그대로 쓴다 (화면에서 지어내지 않는다) -->
    <p v-if="notice" class="banner">{{ notice }}</p>

    <p v-if="loadError" class="error">{{ loadError }}</p>
    <p v-if="loading" class="muted">불러오는 중...</p>

    <p v-else-if="roots && !roots.available" class="muted card">
      후보 작업 폴더가 없습니다 (<code>{{ roots.export }}</code>).
      이 화면은 로컬에서 케이스를 준비할 때 쓰는 도구라, 배포 서버에는 폴더가 없는 것이 정상입니다.
    </p>

    <template v-else-if="candidates.length">
      <!-- 진행 현황 -->
      <div v-if="counts" class="progress card">
        <div class="stat">
          <span class="n">{{ counts.total }}</span><span class="k">전체</span>
        </div>
        <div class="stat">
          <span class="n">{{ counts.technical.unreviewed }}</span><span class="k">미검수</span>
        </div>
        <div class="stat pass">
          <span class="n">{{ counts.technical.tech_pass }}</span><span class="k">TECH PASS</span>
        </div>
        <div class="stat hold">
          <span class="n">{{ counts.technical.hold }}</span><span class="k">HOLD</span>
        </div>
        <div class="stat reject">
          <span class="n">{{ counts.technical.reject_tech }}</span><span class="k">REJECT</span>
        </div>
        <div class="stat expert">
          <span class="n">{{ counts.awaiting_expert_review }}</span>
          <span class="k">전문가 검수 대기</span>
        </div>
      </div>

      <!-- 필터 + 단축키 -->
      <div class="toolbar">
        <div class="segmented">
          <button
            v-for="o in filterOptions"
            :key="o.key"
            :class="{ active: filter === o.key }"
            @click="setFilter(o.key)"
          >
            {{ o.label }} <small>{{ o.n }}</small>
          </button>
        </div>
        <p class="muted keys">
          단축키 — <kbd>←</kbd><kbd>→</kbd> 이동 · <kbd>P</kbd> PASS ·
          <kbd>H</kbd> HOLD · <kbd>R</kbd> REJECT · <kbd>U</kbd> 미검수 ·
          <kbd>Enter</kbd> 확대
        </p>
      </div>

      <p v-if="!filtered.length" class="muted card">이 필터에 해당하는 후보가 없습니다.</p>

      <!-- 카드 그리드 -->
      <div class="grid">
        <article
          v-for="(c, i) in filtered"
          :key="c.case_id"
          :data-case="c.case_id"
          class="case-card"
          :class="[c.review.technical_review_status, { focused: i === cursor }]"
          @click="cursor = i"
        >
          <div class="card-head">
            <strong>{{ c.case_id }}</strong>
            <span class="badge" :class="c.review.technical_review_status">
              {{ TECH_LABEL[c.review.technical_review_status] }}
            </span>
          </div>

          <!-- 검수 시트 -->
          <button
            v-if="sheetUrls[c.case_id]"
            class="sheet"
            :aria-label="`${c.case_id} 검수 시트 확대`"
            @click.stop="((cursor = i), (lightbox = true))"
          >
            <img :src="sheetUrls[c.case_id]" :alt="`${c.case_id} 검수 시트 (병변 시작·대표·끝 slice)`" />
          </button>
          <p v-else-if="sheetErrors[c.case_id]" class="muted sheet-missing">
            검수 시트를 불러오지 못했습니다.
          </p>
          <p v-else class="muted sheet-missing">시트 불러오는 중...</p>

          <!-- 계산된 객관값 (전부 export 단계 산출물) -->
          <dl class="facts">
            <div><dt>편측</dt><dd>{{ c.laterality ?? '미확정' }}</dd></div>
            <div><dt>GT voxel</dt><dd class="tnum">{{ c.gt_voxels?.toLocaleString() }}</dd></div>
            <div><dt>대표 slice</dt><dd class="tnum">{{ c.representative_slice }}</dd></div>
            <div>
              <dt>대표 면적</dt>
              <dd class="tnum">{{ c.representative_area_px?.toLocaleString() }} px</dd>
            </div>
            <div>
              <dt>병변 slice</dt>
              <dd class="tnum">
                {{ c.lesion_slice_count }}장
                <small v-if="c.lesion_slice_range?.[0] != null">
                  ({{ c.lesion_slice_range[0] }}~{{ c.lesion_slice_range[1] }} / 총 {{ c.total_slices }})
                </small>
              </dd>
            </div>
            <div><dt>크기 구간</dt><dd>{{ c.size_bucket_label ?? '—' }}</dd></div>
          </dl>

          <p class="muted tiny">{{ c.size_bucket_basis }}</p>

          <details class="more">
            <summary>선정 근거 · 원본 출처</summary>
            <dl class="facts small">
              <div><dt>선정 근거</dt><dd>{{ c.selection_reason }}</dd></div>
              <div><dt>데이터셋</dt><dd>{{ c.dataset }} / {{ c.source_case_id }}</dd></div>
              <div><dt>ROI</dt><dd>{{ c.provenance.roi_name }} <small>({{ c.provenance.roi_selected_by }})</small></dd></div>
              <div><dt>ROI 후보</dt><dd>{{ (c.provenance.roi_candidates || []).join(', ') }}</dd></div>
              <div><dt>시리즈</dt><dd>{{ c.provenance.series_description }}</dd></div>
              <div><dt>RTSTRUCT</dt><dd class="wrap">{{ c.provenance.rtstruct_file }}</dd></div>
              <div><dt>편측 근거</dt><dd>{{ c.laterality_basis }}</dd></div>
              <div>
                <dt>편측 계산</dt>
                <dd>
                  FOV 기준 {{ c.laterality_detail.by_fov_center }} /
                  머리 기준 {{ c.laterality_detail.by_head_center }}
                  <strong v-if="c.laterality_agree === false" class="warn">— 불일치</strong>
                </dd>
              </div>
              <div><dt>GT 출처</dt><dd>{{ c.provenance.gt_source }}</dd></div>
            </dl>
          </details>

          <!-- 기계 사전점검 -->
          <p class="pre-check" :class="{ flagged: c.pre_check.warnings.length }">
            <span v-if="c.pre_check.warnings.length">
              기계 점검: {{ c.pre_check.warnings.join(', ') }}
            </span>
            <span v-else>
              기계 점검 이상 없음 (덩어리 {{ c.pre_check.components }}개, 배경 위
              {{ Math.round((c.pre_check.on_background_ratio ?? 0) * 100) }}%)
            </span>
          </p>

          <!--
            AI 예측 — GT 와 **완전히 분리된 블록**이다.
            AI 가 못 찾았다는 것이 GT 가 틀렸다는 뜻이 아니다 (VS-SEG-204 가 반례).
          -->
          <div v-if="c.ai_prediction" class="ai-block">
            <div class="ai-head">
              <span class="chip chip-ai">AI 예측 (참고 전용)</span>
              <span class="tnum">
                {{ c.ai_prediction.detected ? '검출' : '미검출' }}
                · Dice {{ c.ai_prediction.dice_vs_reference ?? '—' }}
              </span>
            </div>
            <p class="tiny">{{ c.ai_prediction.notice }}</p>
          </div>

          <!-- 세 상태를 항상 함께 보여준다 -->
          <div class="statuses">
            <span class="status-pill" :class="c.review.technical_review_status">
              기술: {{ TECH_LABEL[c.review.technical_review_status] }}
            </span>
            <span class="status-pill expert">
              {{ EXPERT_LABEL[c.review.expert_review_status] ?? c.review.expert_review_status }}
            </span>
            <span class="status-pill activation">
              {{ ACTIVATION_LABEL[c.review.activation_status] ?? c.review.activation_status }}
            </span>
          </div>

          <!-- 판단 -->
          <div class="actions" @click.stop>
            <button
              class="btn sm pass"
              :class="{ on: c.review.technical_review_status === TECH.PASS }"
              :disabled="savingId === c.case_id"
              @click="decide(c.case_id, TECH.PASS)"
            >
              TECH PASS
            </button>
            <button
              class="btn sm hold"
              :class="{ on: c.review.technical_review_status === TECH.HOLD }"
              :disabled="savingId === c.case_id"
              @click="decide(c.case_id, TECH.HOLD)"
            >
              HOLD
            </button>
            <button
              class="btn sm reject"
              :class="{ on: c.review.technical_review_status === TECH.REJECT }"
              :disabled="savingId === c.case_id"
              @click="decide(c.case_id, TECH.REJECT)"
            >
              REJECT
            </button>
            <span v-if="savedId === c.case_id" class="saved">저장됨</span>
          </div>

          <label class="note" @click.stop>
            <span class="muted tiny">기술 메모 (의료 소견이 아닙니다)</span>
            <input
              v-model="c.review.note"
              type="text"
              maxlength="500"
              placeholder="예: overlay 위치 재확인 / 이미지 대비가 낮아 확인 어려움"
              @keyup.enter="saveNote(c.case_id)"
              @blur="saveNote(c.case_id)"
            />
          </label>

          <p v-if="c.review.reviewed_at" class="muted tiny">
            {{ c.review.reviewer }} · {{ c.review.reviewed_at }}
          </p>
        </article>
      </div>
    </template>

    <p v-else class="muted card">검수할 후보가 없습니다.</p>

    <!-- 확대 보기 -->
    <div v-if="lightbox && current" class="lightbox" @click="lightbox = false">
      <div class="lightbox-bar" @click.stop>
        <strong>{{ current.case_id }}</strong>
        <span class="muted">{{ cursor + 1 }} / {{ filtered.length }}</span>
        <button class="btn sm" @click="move(-1)">← 이전</button>
        <button class="btn sm" @click="move(1)">다음 →</button>
        <button class="btn sm" @click="lightbox = false">닫기 (Esc)</button>
      </div>
      <img
        v-if="sheetUrls[current.case_id]"
        :src="sheetUrls[current.case_id]"
        :alt="`${current.case_id} 검수 시트 확대`"
        @click.stop
      />
    </div>
  </section>
</template>

<style scoped>
.page {
  max-width: 1400px;
  margin: 0 auto;
  padding: var(--sp-6, 24px) var(--sp-4, 16px) 64px;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  flex-wrap: wrap;
}
h1 {
  margin: 0 0 4px;
  font-size: 1.4rem;
}
.banner {
  margin: 14px 0;
  padding: 10px 14px;
  border-radius: 10px;
  background: var(--amber-50, #fff8e6);
  border: 1px solid var(--amber-200, #f3dfa8);
  font-size: 0.9rem;
}
.card {
  padding: 16px;
  border: 1px solid var(--line, rgba(0, 0, 0, 0.1));
  border-radius: 12px;
}

/* 진행 현황 */
.progress {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin: 14px 0;
}
.stat {
  display: flex;
  flex-direction: column;
  min-width: 92px;
  padding: 8px 12px;
  border-radius: 10px;
  background: var(--gray-50, #f6f7f9);
}
.stat .n {
  font-size: 1.3rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.stat .k {
  font-size: 0.78rem;
  color: var(--ink-muted, #667);
}
.stat.pass {
  background: #e8f6ef;
}
.stat.hold {
  background: #fdf3e2;
}
.stat.reject {
  background: #fdeceb;
}
.stat.expert {
  background: #eef1fb;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.keys {
  font-size: 0.8rem;
}
kbd {
  padding: 1px 5px;
  margin: 0 1px;
  border: 1px solid var(--line, rgba(0, 0, 0, 0.15));
  border-bottom-width: 2px;
  border-radius: 4px;
  font-size: 0.75rem;
  background: #fff;
}

/* 카드 */
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(380px, 1fr));
  gap: 16px;
}
.case-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border: 1px solid var(--line, rgba(0, 0, 0, 0.1));
  border-radius: 12px;
  background: #fff;
}
.case-card.focused {
  outline: 2px solid var(--brand-500, #2f62e8);
  outline-offset: 2px;
}
.case-card.tech_pass {
  border-left: 4px solid #1a7f5a;
}
.case-card.hold {
  border-left: 4px solid #b8791f;
}
.case-card.reject_tech {
  border-left: 4px solid #c0392b;
}
.card-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.badge {
  font-size: 0.72rem;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--gray-100, #eceef2);
}
.badge.tech_pass {
  background: #e8f6ef;
  color: #1a7f5a;
}
.badge.hold {
  background: #fdf3e2;
  color: #b8791f;
}
.badge.reject_tech {
  background: #fdeceb;
  color: #c0392b;
}

.sheet {
  padding: 0;
  border: 0;
  background: #000;
  border-radius: 8px;
  overflow: hidden;
  cursor: zoom-in;
  min-height: 44px;
}
.sheet img {
  display: block;
  width: 100%;
  height: auto;
}
.sheet-missing {
  padding: 24px;
  text-align: center;
  background: var(--gray-50, #f6f7f9);
  border-radius: 8px;
  font-size: 0.85rem;
}

.facts {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 4px 12px;
  margin: 0;
  font-size: 0.85rem;
}
.facts.small {
  grid-template-columns: 1fr;
  font-size: 0.8rem;
}
.facts > div {
  display: flex;
  gap: 6px;
}
.facts dt {
  color: var(--ink-muted, #667);
  flex: 0 0 auto;
}
.facts dd {
  margin: 0;
}
.facts dd.wrap {
  word-break: break-all;
}
.tnum {
  font-variant-numeric: tabular-nums;
}
.tiny {
  font-size: 0.75rem;
  margin: 0;
}
.warn {
  color: #c0392b;
}

.more summary {
  cursor: pointer;
  font-size: 0.82rem;
  color: var(--ink-muted, #667);
}

.pre-check {
  margin: 0;
  padding: 6px 10px;
  border-radius: 8px;
  background: var(--gray-50, #f6f7f9);
  font-size: 0.8rem;
}
.pre-check.flagged {
  background: #fdf3e2;
  color: #8a5a12;
}

/* AI 예측 — GT 와 시각적으로 완전히 분리 */
.ai-block {
  padding: 8px 10px;
  border: 1px dashed #7b61c9;
  border-radius: 8px;
  background: #f6f3fd;
}
.ai-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  font-size: 0.82rem;
}
.chip-ai {
  padding: 2px 8px;
  border-radius: 999px;
  background: #7b61c9;
  color: #fff;
  font-size: 0.72rem;
}

.statuses {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.status-pill {
  font-size: 0.72rem;
  padding: 3px 8px;
  border-radius: 6px;
  background: var(--gray-100, #eceef2);
}
.status-pill.tech_pass {
  background: #e8f6ef;
  color: #1a7f5a;
}
.status-pill.hold {
  background: #fdf3e2;
  color: #b8791f;
}
.status-pill.reject_tech {
  background: #fdeceb;
  color: #c0392b;
}
.status-pill.expert {
  background: #eef1fb;
  color: #3b4a8c;
}
.status-pill.activation {
  background: #f2f2f4;
  color: #555;
}

.actions {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.btn.sm.pass.on {
  background: #1a7f5a;
  color: #fff;
}
.btn.sm.hold.on {
  background: #b8791f;
  color: #fff;
}
.btn.sm.reject.on {
  background: #c0392b;
  color: #fff;
}
.saved {
  font-size: 0.78rem;
  color: #1a7f5a;
}

.note {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.note input {
  width: 100%;
}

/* 확대 보기 */
.lightbox {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: rgba(0, 0, 0, 0.9);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 16px;
}
.lightbox img {
  max-width: 100%;
  max-height: calc(100vh - 110px);
  object-fit: contain;
}
.lightbox-bar {
  display: flex;
  gap: 10px;
  align-items: center;
  color: #fff;
  background: rgba(0, 0, 0, 0.6);
  padding: 8px 14px;
  border-radius: 10px;
}
.lightbox-bar .muted {
  color: #bbb;
}
</style>
