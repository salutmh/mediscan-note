<script setup>
/**
 * 운영자 화면 — 최소 콘텐츠 관리 (docs/api-spec.md 2-A)
 *
 * 목적은 "개발자가 DB·CLI 를 직접 만지지 않고 콘텐츠를 다룰 수 있게" 하는 것이다.
 * 거대한 CMS 를 만들지 않는다. 여기서 다루는 것은 **운영 메타데이터와 전문가 소견**뿐이다.
 *
 * 여기서 못 하는 것 (의도적):
 *   - 영상·마스크 업로드      등록은 4단계 파이프라인을 거친다 (사람이 검수하는 지점을 없애지 않는다)
 *   - 기준 마스크(GT) 수정    채점 기준을 화면에서 고치는 경로를 만들지 않는다
 *   - 케이스 삭제             제출 이력까지 지우는 파괴적 작업이라 CLI 에 둔다. 여기서는 숨김만
 *
 * 권한 차단은 **서버가** 한다 (403 ADMIN_REQUIRED). 이 화면의 숨김은 UX 일 뿐이다.
 */
import { onMounted, ref } from 'vue'
import {
  adminDeleteFindings,
  adminIssueResetCode,
  adminLearningSummary,
  adminListCases,
  adminSaveFindings,
  adminUpdateCase,
} from '../api/endpoints'

const cases = ref([])
const loading = ref(true)
const error = ref('')
const notice = ref('')
const forbidden = ref(false)

// 소견 편집 중인 케이스 (한 번에 하나만)
const editing = ref(null)
const form = ref(null)
const saving = ref(false)

const DIFFICULTIES = [
  { value: '', label: '미지정' },
  { value: 'easy', label: '쉬움' },
  { value: 'medium', label: '보통' },
  { value: 'hard', label: '어려움' },
]
const STATUS_LABEL = {
  needs_expert_review: '검토 전',
  in_review: '검토 중',
  approved: '검토 완료',
}

/**
 * 학습 지표 — "학습이 실제로 일어나는가"를 운영자가 서버 접속 없이 볼 수 있게 한다.
 * 집계만 오고 개인 학습 내용은 나오지 않는다.
 */
const summary = ref(null)

async function load() {
  loading.value = true
  error.value = ''
  try {
    cases.value = (await adminListCases()).cases
  } catch (e) {
    if (e.status === 403) forbidden.value = true
    else error.value = e.message
  } finally {
    loading.value = false
  }
  // 지표 조회가 실패해도 케이스 관리는 되어야 한다 — 조용히 넘어간다
  try {
    summary.value = await adminLearningSummary()
  } catch {
    summary.value = null
  }
}

/** 서버 응답으로 해당 행만 교체한다 (전체 재조회보다 깜빡임이 적다) */
function replaceRow(updated) {
  const i = cases.value.findIndex((c) => c.case_id === updated.case_id)
  if (i >= 0) cases.value[i] = { ...cases.value[i], ...updated }
}

async function patchCase(caseId, patch, message) {
  error.value = ''
  notice.value = ''
  try {
    replaceRow(await adminUpdateCase(caseId, patch))
    notice.value = message
  } catch (e) {
    error.value = e.message
  }
}

const toggleActive = (c) =>
  patchCase(
    c.case_id,
    { is_active: !c.is_active },
    c.is_active ? `${c.case_id} 을(를) 숨겼습니다.` : `${c.case_id} 을(를) 다시 노출했습니다.`,
  )

const changeDifficulty = (c, value) =>
  patchCase(c.case_id, { difficulty: value }, `${c.case_id} 난이도를 변경했습니다.`)

const changeStatus = (c, value) =>
  patchCase(c.case_id, { findings_status: value }, `${c.case_id} 검토 상태를 변경했습니다.`)

// ---------------------------------------------------------------- 소견 편집
function startEditing(c) {
  editing.value = c.case_id
  notice.value = ''
  error.value = ''
  // 새로 쓰는 폼만 제공한다. 기존 소견을 불러와 수정하려면 상세 조회가 필요한데,
  // 지금 필요한 것은 "없는 소견을 채우는 것"이라 최소 형태로 둔다.
  form.value = {
    findings: '',
    reviewer: '',
    reviewed_at: new Date().toISOString().slice(0, 10),
    lesion_location: '',
    reference_region_note: '',
    learning_points: '',
    common_mistakes: '',
  }
}

function cancelEditing() {
  editing.value = null
  form.value = null
}

/** 줄바꿈으로 나눈 뒤 빈 줄은 버린다 — 빈 항목을 만들어 넣지 않는다 */
const toList = (text) =>
  text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)

async function saveFindings(caseId) {
  saving.value = true
  error.value = ''
  try {
    const payload = {
      findings: form.value.findings,
      reviewer: form.value.reviewer,
      reviewed_at: form.value.reviewed_at,
      lesion_location: form.value.lesion_location || null,
      reference_region_note: form.value.reference_region_note || null,
      learning_points: toList(form.value.learning_points),
      common_mistakes: toList(form.value.common_mistakes),
    }
    await adminSaveFindings(caseId, payload)
    cancelEditing()
    await load()
    notice.value = `${caseId} 소견을 등록했습니다.`
  } catch (e) {
    error.value = e.message
  } finally {
    saving.value = false
  }
}

async function removeFindings(caseId) {
  error.value = ''
  try {
    await adminDeleteFindings(caseId)
    await load()
    notice.value = `${caseId} 소견을 회수했습니다.`
  } catch (e) {
    error.value = e.message
  }
}

/**
 * 비밀번호 재설정 코드 발급.
 *
 * 메일 발송 수단이 없어 "비밀번호 찾기"를 만들 수 없다. 운영자가 코드를 발급하고
 * **본인 확인은 오프라인으로** 한다. 코드는 응답에만 있고 다시 볼 수 없으므로
 * 그 자리에서 전달해야 한다.
 */
const resetEmail = ref('')
const resetBusy = ref(false)
const resetResult = ref(null)
const resetError = ref('')

async function issueResetCode() {
  resetBusy.value = true
  resetError.value = ''
  resetResult.value = null
  try {
    resetResult.value = await adminIssueResetCode(resetEmail.value.trim())
    resetEmail.value = ''
  } catch (e) {
    resetError.value = e.message
  } finally {
    resetBusy.value = false
  }
}

onMounted(load)
</script>

<template>
  <section class="page">
    <header class="page-head">
      <h1>콘텐츠 관리</h1>
      <p class="muted">
        운영 메타데이터와 전문가 소견만 다룹니다. 영상·기준 마스크 등록은 파이프라인
        (<code>scripts/import_cases.py</code>)을 거칩니다.
      </p>
    </header>

    <p v-if="forbidden" class="notice error">
      운영자 권한이 필요합니다. 권한은 서버에서만 부여할 수 있습니다
      (<code>python -m scripts.grant_admin --email &lt;이메일&gt;</code>).
    </p>

    <template v-else>
      <p v-if="error" class="notice error">{{ error }}</p>
      <p v-if="notice" class="notice ok">{{ notice }}</p>
      <p v-if="loading" class="muted">불러오는 중…</p>

      <!-- 학습 지표 (집계) -->
      <section v-if="summary" class="summary">
        <div class="summary-head">
          <h2>학습 지표</h2>
          <span class="muted">집계만 표시합니다 · 개인 학습 내용은 포함되지 않습니다</span>
        </div>

        <p v-if="!summary.analytics_enabled" class="notice">
          학습 이벤트 수집이 꺼져 있습니다 (<code>MEDISCAN_ANALYTICS=0</code>).
          아래 수치는 그 이전에 쌓인 것입니다.
        </p>
        <p v-else-if="!summary.events" class="muted">
          아직 기록된 학습 활동이 없습니다. 사용자가 케이스를 열고 제출하면 쌓입니다.
        </p>

        <dl v-else class="stat-row">
          <div>
            <dt>참여자</dt>
            <dd class="tnum">{{ summary.users_seen }}명</dd>
          </div>
          <div>
            <dt>시작 → 제출 전환율</dt>
            <dd class="tnum">
              {{ summary.start_to_submit_rate == null ? '—'
                : Math.round(summary.start_to_submit_rate * 100) + '%' }}
            </dd>
          </div>
          <div>
            <dt>첫 시도 평균 Dice</dt>
            <dd class="tnum">{{ summary.first_attempt_mean_dice ?? '—' }}</dd>
          </div>
          <div>
            <dt>재도전 평균 Dice</dt>
            <dd class="tnum">{{ summary.retry_mean_dice ?? '—' }}</dd>
          </div>
          <div>
            <dt>재도전 시 점수 변화</dt>
            <dd class="tnum" :class="{ up: (summary.mean_improvement ?? 0) > 0 }">
              {{ summary.mean_improvement == null ? '—'
                : (summary.mean_improvement > 0 ? '+' : '') + summary.mean_improvement }}
            </dd>
          </div>
          <div>
            <dt>평균 소요시간</dt>
            <dd class="tnum">
              {{ summary.mean_duration_seconds == null ? '—'
                : Math.round(summary.mean_duration_seconds) + '초' }}
            </dd>
          </div>
          <!-- 해설을 읽지 않는다면 소견 작성에 사람 시간을 더 쓸 이유가 줄어든다.
               전문가 검수 우선순위를 정하는 데 쓰는 값이다. -->
          <div>
            <dt>해설 열람률</dt>
            <dd class="tnum">
              {{ summary.submit_to_explanation_rate == null ? '—'
                : Math.round(summary.submit_to_explanation_rate * 100) + '%' }}
              <small v-if="summary.explanations_viewed != null">
                ({{ summary.explanations_viewed }}건)
              </small>
            </dd>
          </div>
        </dl>
      </section>

      <table v-if="!loading" class="admin-table">
        <thead>
          <tr>
            <th>케이스</th>
            <th>상태</th>
            <th>난이도</th>
            <th>검토 상태</th>
            <th>제출</th>
            <th>소견</th>
          </tr>
        </thead>
        <tbody>
          <template v-for="c in cases" :key="c.case_id">
            <tr :class="{ inactive: !c.is_active }">
              <td>
                <strong>{{ c.case_id }}</strong>
                <div class="sub muted">{{ c.body_part }} · {{ c.disease }}</div>
                <div v-if="!c.gradable" class="sub warn">기준 마스크 없음 (채점 불가)</div>
              </td>
              <td>
                <button class="sm" @click="toggleActive(c)">
                  {{ c.is_active ? '노출 중' : '숨김' }}
                </button>
              </td>
              <td>
                <select
                  :value="c.difficulty ?? ''"
                  @change="changeDifficulty(c, $event.target.value)"
                >
                  <option v-for="d in DIFFICULTIES" :key="d.value" :value="d.value">
                    {{ d.label }}
                  </option>
                </select>
              </td>
              <td>
                <select
                  :value="c.case_findings_status"
                  :disabled="c.has_case_findings"
                  @change="changeStatus(c, $event.target.value)"
                >
                  <option v-for="(label, value) in STATUS_LABEL" :key="value" :value="value">
                    {{ label }}
                  </option>
                </select>
              </td>
              <td class="tnum">{{ c.submission_count }}</td>
              <td>
                <button v-if="!c.has_case_findings" class="sm" @click="startEditing(c)">
                  소견 등록
                </button>
                <button v-else class="sm ghost" @click="removeFindings(c.case_id)">회수</button>
              </td>
            </tr>

            <tr v-if="editing === c.case_id" class="editor-row">
              <td colspan="6">
                <form class="editor" @submit.prevent="saveFindings(c.case_id)">
                  <p class="editor-note">
                    <strong>전문가가 작성한 내용만 입력하세요.</strong>
                    검토자와 검토일은 필수입니다 — 누가 언제 본 내용인지 남지 않는 소견은
                    등록되지 않습니다.
                  </p>
                  <label>
                    <span>영상 소견 <em>*</em></span>
                    <textarea v-model="form.findings" rows="3" required></textarea>
                  </label>
                  <div class="grid2">
                    <label>
                      <span>검토자 <em>*</em></span>
                      <input v-model="form.reviewer" required />
                    </label>
                    <label>
                      <span>검토일 <em>*</em></span>
                      <input v-model="form.reviewed_at" type="date" required />
                    </label>
                  </div>
                  <label>
                    <span>병변 위치</span>
                    <input v-model="form.lesion_location" />
                  </label>
                  <label>
                    <span>기준 영역 설명</span>
                    <input v-model="form.reference_region_note" />
                  </label>
                  <div class="grid2">
                    <label>
                      <span>확인할 점 (한 줄에 하나)</span>
                      <textarea v-model="form.learning_points" rows="3"></textarea>
                    </label>
                    <label>
                      <span>자주 놓치는 부분 (한 줄에 하나)</span>
                      <textarea v-model="form.common_mistakes" rows="3"></textarea>
                    </label>
                  </div>
                  <div class="editor-actions">
                    <button type="submit" :disabled="saving">
                      {{ saving ? '저장 중…' : '등록' }}
                    </button>
                    <button type="button" class="ghost" @click="cancelEditing">취소</button>
                  </div>
                </form>
              </td>
            </tr>
          </template>
        </tbody>
      </table>
      <!-- 운영 도구 -->
      <section class="tools">
        <div class="summary-head">
          <h2>비밀번호 재설정 코드 발급</h2>
          <span class="muted">본인 확인 후 발급하세요 · 코드는 다시 볼 수 없습니다</span>
        </div>

        <form class="tool-form" @submit.prevent="issueResetCode">
          <input
            v-model.trim="resetEmail"
            type="email"
            required
            placeholder="사용자 이메일"
            aria-label="재설정 코드를 발급할 사용자 이메일"
          />
          <button type="submit" :disabled="resetBusy">
            {{ resetBusy ? '발급 중…' : '코드 발급' }}
          </button>
        </form>

        <p v-if="resetError" class="notice error">{{ resetError }}</p>

        <div v-if="resetResult" class="notice ok reset-issued">
          <p>
            <strong>{{ resetResult.user_id }}</strong> 의 재설정 코드:
            <code class="reset-code">{{ resetResult.code }}</code>
          </p>
          <p class="muted">
            24시간 동안 <strong>한 번만</strong> 쓸 수 있습니다.
            이 화면을 벗어나면 다시 볼 수 없으니 지금 전달하세요.
            사용자는 로그인 화면의 "비밀번호 재설정"에서 입력합니다.
          </p>
        </div>
      </section>
    </template>
  </section>
</template>

<style scoped>
.page {
  max-width: 1040px;
  margin: 0 auto;
  padding: var(--sp-6) var(--sp-4);
}

.page-head h1 {
  margin: 0 0 var(--sp-1);
  font-size: 22px;
}

.page-head p {
  margin: 0 0 var(--sp-5);
  font-size: 13px;
}

/* 학습 지표 — 케이스 표와 시각적으로 분리한다 (다른 성격의 정보다) */
.summary {
  padding: var(--sp-4);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface-sunken);
  margin-bottom: var(--sp-5);
}

.summary-head {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
  flex-wrap: wrap;
  margin-bottom: var(--sp-3);
}

.summary-head h2 {
  margin: 0;
  font-size: 14px;
}

.summary-head span {
  font-size: 11.5px;
}

.stat-row {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-5);
  margin: 0;
}

.stat-row dt {
  font-size: 11.5px;
  color: var(--ink-muted);
  font-weight: 600;
}

.stat-row dd {
  margin: 2px 0 0;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.02em;
}

/* 재도전에서 점수가 올랐다는 것은 학습이 일어났다는 최소 신호다 */
.stat-row dd.up {
  color: var(--match-ink);
}

/* 운영 도구 — 콘텐츠 관리와 성격이 다르므로 아래에 따로 둔다 */
.tools {
  margin-top: var(--sp-6);
  padding: var(--sp-4);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
}

.tool-form {
  display: flex;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.tool-form input {
  flex: 1 1 240px;
}

.reset-code {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 2px 8px;
}

.reset-issued p {
  margin: 0 0 var(--sp-2);
}

.admin-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13.5px;
}

.admin-table th,
.admin-table td {
  padding: var(--sp-3);
  border-bottom: 1px solid var(--line);
  text-align: left;
  vertical-align: top;
}

.admin-table th {
  font-size: 12px;
  color: var(--ink-muted);
  font-weight: 700;
}

tr.inactive {
  opacity: 0.55;
}

.sub {
  font-size: 11.5px;
  margin-top: 2px;
}

.warn {
  color: var(--mismatch-ink);
}

button.sm {
  padding: 4px 10px;
  font-size: 12px;
}

.editor-row td {
  background: var(--surface-sunken);
}

.editor {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.editor-note {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: var(--ink-secondary);
}

.editor label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-secondary);
}

.editor em {
  color: var(--mismatch-ink);
  font-style: normal;
}

.grid2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-3);
}

.editor-actions {
  display: flex;
  gap: var(--sp-2);
}

@media (max-width: 720px) {
  .grid2 {
    grid-template-columns: 1fr;
  }
}
</style>
