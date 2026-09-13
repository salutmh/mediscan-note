<script setup>
/**
 * 계정 설정 — 지금은 회원 탈퇴 하나뿐이다.
 *
 * **왜 화면이 필요한가**
 * 의료영상(민감정보)을 다루는 서비스에서 사용자가 자기 계정과 데이터를 지울 방법이
 * 없으면 안 된다. API(DELETE /api/auth/me)만 있고 화면이 없으면 사실상 없는 기능이다.
 *
 * 되돌릴 수 없는 동작이라 두 단계로 막는다:
 *   1) "탈퇴하겠다" 확인
 *   2) 이메일 계정이면 비밀번호 재입력 (SNS 계정은 확인할 비밀번호가 없어 생략)
 * 브라우저 confirm() 은 쓰지 않는다 — 무엇이 지워지는지 화면에 적어 보여준다.
 */
import { computed, onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { changePassword, deleteAccount, getDashboard, getMe, updateProfile } from '../api/endpoints'
import { authState, clearSession, replaceToken } from '../stores/auth'

const router = useRouter()

const confirming = ref(false)
const password = ref('')
const busy = ref(false)
const error = ref('')
const result = ref(null)

// SNS 가입자는 비밀번호가 없다 (서버도 이 경우 비밀번호를 요구하지 않는다)
const isEmailAccount = computed(() => Boolean(authState.user?.email))

/* ---------------------------------------------------------------- 프로필
   시안 11 의 설정 행. **전부 선택 항목이다** — 비어 있어도 학습에 아무 지장이 없다.
   시안의 "학습 수준"은 넣지 않았다: 우리에겐 수준을 쓰는 곳이 없어서
   **아무것도 하지 않는 설정**이 된다 (죽은 컨트롤을 만들지 않는다).
------------------------------------------------------------------------- */
const JOB_ROLES = [
  { code: 'medical_student', label: '의대생' },
  { code: 'radiology_student', label: '방사선학과 학생' },
  { code: 'radiology_resident', label: '영상의학과 학생' },
  { code: 'nursing_student', label: '간호대생' },
]
const jobRoleLabel = (code) => JOB_ROLES.find((r) => r.code === code)?.label ?? null

const profile = ref({ job_role: null, birth_date: null, school: null, major: null })
const editing = ref('') // '' | 'basic' | 'role'
const profileDraft = ref({})
const profileBusy = ref(false)
const profileError = ref('')

/** 시안 11 하단의 지표 3칸 */
const stats = ref(null)

onMounted(async () => {
  try {
    const me = await getMe()
    profile.value = me.profile ?? profile.value
  } catch {
    // 프로필을 못 불러와도 계정 화면의 본래 기능(비밀번호·탈퇴)은 그대로 쓸 수 있어야 한다
  }
  try {
    stats.value = await getDashboard()
  } catch {
    stats.value = null
  }
})

function startEdit(which) {
  editing.value = which
  profileError.value = ''
  profileDraft.value = { ...profile.value }
}

async function saveProfile() {
  profileBusy.value = true
  profileError.value = ''
  try {
    const saved = await updateProfile(profileDraft.value)
    profile.value = saved.profile
    editing.value = ''
  } catch (e) {
    profileError.value = e.message || '저장하지 못했습니다.'
  } finally {
    profileBusy.value = false
  }
}

function percent(value) {
  return value == null ? null : Math.round(value * 100)
}

/** 기준과 일치한 비율 — 분모는 **시도한 케이스**다 (대시보드와 같은 규칙) */
const matchRate = computed(() => {
  const t = stats.value?.totals
  if (!t?.attempted) return null
  return Math.round((t.matched / t.attempted) * 100)
})

const DELETED_LABEL = {
  consents: '동의 이력',
  submissions: '제출·채점 이력',
  learning_events: '학습 기록',
}

// ---------------------------------------------------------------- 비밀번호
const pw = ref({ current: '', next: '', confirm: '' })
const pwBusy = ref(false)
const pwError = ref('')
const pwDone = ref(false)

const MIN_PASSWORD_LENGTH = 8

async function submitPassword() {
  pwError.value = ''
  pwDone.value = false

  if (pw.value.next.length < MIN_PASSWORD_LENGTH) {
    pwError.value = `새 비밀번호는 ${MIN_PASSWORD_LENGTH}자 이상이어야 합니다.`
    return
  }
  if (pw.value.next !== pw.value.confirm) {
    // 서버까지 갈 필요 없는 오타는 여기서 잡는다
    pwError.value = '새 비밀번호가 서로 다릅니다.'
    return
  }

  pwBusy.value = true
  try {
    const result = await changePassword({
      current_password: pw.value.current,
      new_password: pw.value.next,
    })
    // 다른 기기는 끊기고 이 기기만 새 토큰으로 이어진다
    replaceToken(result.access_token)
    pwDone.value = true
    pw.value = { current: '', next: '', confirm: '' }
  } catch (e) {
    pwError.value = e.message
  } finally {
    pwBusy.value = false
  }
}

function cancel() {
  confirming.value = false
  password.value = ''
  error.value = ''
}

async function submit() {
  busy.value = true
  error.value = ''
  try {
    result.value = await deleteAccount(isEmailAccount.value ? password.value : undefined)
    // 계정이 사라졌고 서버가 그 토큰을 이미 폐기했다. 로컬만 비우면 된다 —
    // 여기서 서버 로그아웃을 또 부르면 401 만 돌아온다.
    clearSession()
  } catch (e) {
    error.value = e.message
  } finally {
    busy.value = false
    password.value = ''
  }
}

function goHome() {
  router.push({ name: 'login' })
}
</script>

<template>
  <section class="page-narrow">
    <h1>계정 설정</h1>

    <!-- 탈퇴 완료 -->
    <div v-if="result" class="card done">
      <h2>탈퇴가 완료되었습니다</h2>
      <p>계정과 아래 데이터가 모두 삭제되었습니다.</p>
      <ul>
        <li v-for="(count, key) in result.deleted_counts" :key="key">
          {{ DELETED_LABEL[key] ?? key }} {{ count }}건
        </li>
      </ul>
      <p class="muted">같은 이메일로 다시 가입할 수 있습니다.</p>
      <button @click="goHome">처음 화면으로</button>
    </div>

    <template v-else>
      <!-- 시안 11 의 프로필 카드. **시안의 학교·학과·직군은 넣지 않는다** —
           우리는 가입할 때 그런 정보를 받지 않는다. 없는 칸을 만들지 않는다. -->
      <div class="card profile">
        <span class="profile-avatar" aria-hidden="true">
          {{ (authState.user?.nickname ?? '?').trim().charAt(0) || '?' }}
        </span>
        <div class="profile-info">
          <strong class="profile-name">{{ authState.user?.nickname ?? '사용자' }}</strong>
          <p class="profile-meta">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
              <path d="M4 6h16v12H4z" /><path d="M4 7l8 6 8-6" />
            </svg>
            {{ authState.user?.email ?? '간편 로그인 (개발용 예시)' }}
          </p>
          <span class="profile-chip">{{ isEmailAccount ? '이메일 계정' : '간편 로그인 계정' }}</span>
        </div>
      </div>

      <!-- 시안 11 의 설정 행 -->
      <div class="card rows-card">
        <h2 class="card-title">기본정보</h2>

        <!-- 1) 닉네임 · 학교 · 전공 -->
        <div class="set-row">
          <span class="chip" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <circle cx="12" cy="8" r="3.5" /><path d="M5 20v-2a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v2" />
            </svg>
          </span>
          <span class="set-text">
            <strong>프로필</strong>
            <small v-if="profile.school || profile.major || profile.birth_date">
              {{ [profile.school, profile.major, profile.birth_date].filter(Boolean).join(' · ') }}
            </small>
            <!-- **비어 있는 것이 정상이다.** 채우라고 재촉하지 않는다 -->
            <small v-else>학교·전공은 선택 항목입니다. 비워 두어도 됩니다.</small>
          </span>
          <button class="sm" @click="startEdit(editing === 'basic' ? '' : 'basic')">
            {{ editing === 'basic' ? '닫기' : '수정하기' }}
          </button>
        </div>

        <form v-if="editing === 'basic'" class="set-form" @submit.prevent="saveProfile">
          <label class="field">
            <span>생년월일</span>
            <input v-model="profileDraft.birth_date" type="date" />
          </label>
          <label class="field">
            <span>학교</span>
            <input v-model.trim="profileDraft.school" type="text" placeholder="예: 메드렌즈대학교" />
          </label>
          <label class="field">
            <span>전공</span>
            <input v-model.trim="profileDraft.major" type="text" placeholder="예: 방사선학과" />
          </label>
          <button class="primary" type="submit" :disabled="profileBusy">
            {{ profileBusy ? '저장 중…' : '저장' }}
          </button>
        </form>

        <!-- 2) 직군 -->
        <div class="set-row">
          <span class="chip" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M4 20v-2a4 4 0 0 1 4-4h3" /><circle cx="9.5" cy="8" r="3" />
              <path d="M15 13l2 2 4-4" />
            </svg>
          </span>
          <span class="set-text">
            <strong>직군</strong>
            <small>{{ jobRoleLabel(profile.job_role) ?? '아직 고르지 않았습니다' }}</small>
          </span>
          <button class="sm" @click="startEdit(editing === 'role' ? '' : 'role')">
            {{ editing === 'role' ? '닫기' : '수정하기' }}
          </button>
        </div>

        <div v-if="editing === 'role'" class="set-form">
          <div class="role-chips">
            <button
              v-for="r in JOB_ROLES"
              :key="r.code"
              class="role-chip"
              :class="{ active: profileDraft.job_role === r.code }"
              :aria-pressed="profileDraft.job_role === r.code"
              @click="profileDraft.job_role = profileDraft.job_role === r.code ? null : r.code"
            >
              {{ r.label }}
            </button>
          </div>
          <p class="muted note">
            직군으로 잠기거나 열리는 기능은 없습니다. 학습자 배경일 뿐입니다.
          </p>
          <button class="primary" :disabled="profileBusy" @click="saveProfile">
            {{ profileBusy ? '저장 중…' : '저장' }}
          </button>
        </div>

        <p v-if="profileError" class="error">{{ profileError }}</p>
      </div>

      <!-- 시안 11 하단의 지표 3칸 -->
      <div v-if="stats" class="card stat-row">
        <div class="stat">
          <span class="chip sm" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M4 12.5l5 5L20 7" />
            </svg>
          </span>
          <span class="stat-text">
            <small>학습완료</small>
            <strong class="tnum">{{ stats.totals.matched }}<em>/ {{ stats.totals.total_cases }}</em></strong>
          </span>
        </div>
        <div class="stat">
          <span class="chip sm" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <circle cx="12" cy="12" r="8" /><circle cx="12" cy="12" r="3" />
            </svg>
          </span>
          <span class="stat-text">
            <small>기준과 일치한 비율</small>
            <strong v-if="matchRate != null" class="tnum">{{ matchRate }}<em>%</em></strong>
            <strong v-else class="empty">아직 기록 없음</strong>
          </span>
        </div>
        <RouterLink class="stat link" to="/wrong-notes">
          <span class="chip sm" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
              <path d="M8 4h8a2 2 0 0 1 2 2v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V6a2 2 0 0 1 2-2z" />
              <path d="M9 3h6v3H9z" />
            </svg>
          </span>
          <span class="stat-text">
            <small>복습 필요</small>
            <strong class="tnum">{{ stats.totals.needs_review }}<em>건</em></strong>
          </span>
        </RouterLink>
      </div>

      <!-- 비밀번호 변경 — 이메일 계정만 -->
      <div v-if="isEmailAccount" class="card">
        <h2>비밀번호 변경</h2>
        <p class="muted note">
          비밀번호를 바꾸면 <strong>다른 기기의 로그인이 모두 해제됩니다.</strong>
          이 기기에서는 그대로 계속 사용할 수 있습니다.
        </p>

        <p v-if="pwError" class="notice error">{{ pwError }}</p>
        <p v-if="pwDone" class="notice ok">
          비밀번호를 변경했습니다. 다른 기기에서는 다시 로그인해야 합니다.
        </p>

        <form class="confirm" @submit.prevent="submitPassword">
          <label>
            <span>현재 비밀번호</span>
            <input v-model="pw.current" type="password" required autocomplete="current-password" />
          </label>
          <label>
            <span>새 비밀번호 ({{ MIN_PASSWORD_LENGTH }}자 이상)</span>
            <input v-model="pw.next" type="password" required autocomplete="new-password" />
          </label>
          <label>
            <span>새 비밀번호 확인</span>
            <input v-model="pw.confirm" type="password" required autocomplete="new-password" />
          </label>
          <div class="actions">
            <button type="submit" :disabled="pwBusy">
              {{ pwBusy ? '변경 중…' : '비밀번호 변경' }}
            </button>
          </div>
        </form>
      </div>

      <div class="card danger">
        <h2>회원 탈퇴</h2>
        <p>
          탈퇴하면 <strong>계정과 학습 기록이 모두 삭제되며 되돌릴 수 없습니다.</strong>
        </p>
        <ul class="scope">
          <li>계정 정보 (이메일 · 닉네임)</li>
          <li>동의 이력</li>
          <li>제출·채점 이력 (복습노트와 진행현황도 함께 사라집니다)</li>
          <li>학습 기록</li>
        </ul>

        <p v-if="error" class="notice error">{{ error }}</p>

        <button v-if="!confirming" class="danger-btn" @click="confirming = true">
          탈퇴하기
        </button>

        <form v-else class="confirm" @submit.prevent="submit">
          <label v-if="isEmailAccount">
            <span>확인을 위해 비밀번호를 다시 입력해 주세요</span>
            <input v-model="password" type="password" required autocomplete="current-password" />
          </label>
          <p v-else class="muted">
            간편 로그인 계정이라 비밀번호 확인 없이 진행됩니다.
          </p>
          <div class="actions">
            <button type="submit" class="danger-btn" :disabled="busy">
              {{ busy ? '삭제 중…' : '영구 삭제' }}
            </button>
            <button type="button" class="ghost" @click="cancel">취소</button>
          </div>
        </form>
      </div>
    </template>
  </section>
</template>

<style scoped>
/* --- 설정 행 (시안 11) --- */
.rows-card {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.set-row {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) 0;
  border-top: 1px solid var(--line);
}
.set-row:first-of-type {
  border-top: 0;
}
.set-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  flex: 1;
  min-width: 0;
}
.set-text strong {
  color: var(--navy-700);
  font-size: 14px;
}
.set-text small {
  color: var(--ink-muted);
  font-size: 12.5px;
  line-height: 1.5;
}
.set-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-4);
  margin-bottom: var(--sp-2);
  border-radius: var(--r-md);
  background: var(--gray-25);
  border: 1px solid var(--line);
}
.role-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}
.role-chip {
  min-height: 38px;
  padding: 8px 16px;
  border-radius: var(--r-full);
  font-size: 13px;
}
/* 고른 것을 **테두리·굵기까지** 바꿔 알린다 (색만으로 구분하지 않는다) */
.role-chip.active {
  border-color: var(--brand-500);
  background: var(--brand-50);
  color: var(--brand-700);
  font-weight: 700;
}

/* --- 하단 지표 (시안 11) --- */
.stat-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0;
  padding: var(--sp-5) 0;
}
.stat {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 0 var(--sp-5);
  min-width: 0;
  text-decoration: none;
  color: inherit;
}
.stat + .stat {
  border-left: 1px solid var(--line);
}
.stat.link:hover strong {
  color: var(--brand-600);
}
.stat-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.stat-text small {
  color: var(--ink-muted);
  font-size: 12px;
}
.stat-text strong {
  font-size: 22px;
  font-weight: 800;
  letter-spacing: -0.03em;
  color: var(--navy-700);
}
.stat-text strong em {
  margin-left: 3px;
  font-size: 13px;
  font-weight: 600;
  font-style: normal;
  color: var(--ink-muted);
}
.stat-text strong.empty {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink-muted);
}

@media (max-width: 760px) {
  .stat-row {
    grid-template-columns: 1fr;
    row-gap: var(--sp-4);
  }
  .stat + .stat {
    border-left: 0;
  }
}

/* --- 프로필 카드 (시안 11) --- */
.profile {
  display: flex;
  align-items: center;
  gap: var(--sp-5);
}
.profile-avatar {
  display: grid;
  place-items: center;
  flex: none;
  width: 64px;
  height: 64px;
  border-radius: var(--r-full);
  background: var(--brand-50);
  color: var(--brand-700);
  font-size: 26px;
  font-weight: 700;
}
.profile-info {
  min-width: 0;
}
.profile-name {
  display: block;
  font-size: 18px;
  color: var(--navy-700);
}
.profile-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 4px 0 var(--sp-2);
  color: var(--ink-muted);
  font-size: 13px;
  overflow-wrap: anywhere;
}
.profile-meta svg {
  width: 15px;
  height: 15px;
  flex: none;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.profile-chip {
  display: inline-block;
  padding: 3px 10px;
  border-radius: var(--r-full);
  background: var(--gray-50);
  border: 1px solid var(--line);
  color: var(--ink-secondary);
  font-size: 11.5px;
  font-weight: 600;
}

.page-narrow {
  max-width: 620px;
  margin: 0 auto;
  padding: var(--sp-6) var(--sp-4);
}

h1 {
  font-size: 22px;
  margin: 0 0 var(--sp-5);
}

.card {
  padding: var(--sp-5);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
  margin-bottom: var(--sp-4);
}

.card h2 {
  margin: 0 0 var(--sp-3);
  font-size: 15px;
}

.card.danger {
  border-color: var(--mismatch-line);
  background: var(--mismatch-bg);
}

.card.danger h2 {
  color: var(--mismatch-ink);
}

.rows div {
  display: flex;
  gap: var(--sp-4);
  padding: 6px 0;
  font-size: 13.5px;
}

.rows dt {
  min-width: 92px;
  color: var(--ink-muted);
  font-size: 12px;
  font-weight: 600;
}

.rows dd {
  margin: 0;
  font-size: 13.5px;
  font-weight: 500;
}

.scope {
  margin: var(--sp-2) 0 var(--sp-4);
  padding-left: 18px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--ink-secondary);
}

.danger-btn {
  background: var(--mismatch-ink);
  border-color: var(--mismatch-ink);
  color: #fff;
}

.danger-btn:hover:not(:disabled) {
  filter: brightness(1.08);
}

.confirm {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.confirm label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--ink-secondary);
}

.actions {
  display: flex;
  gap: var(--sp-2);
}

.note {
  margin: 0 0 var(--sp-3);
  font-size: 12.5px;
  line-height: 1.55;
}

.card.done ul {
  padding-left: 18px;
  font-size: 13.5px;
  line-height: 1.7;
}
</style>
