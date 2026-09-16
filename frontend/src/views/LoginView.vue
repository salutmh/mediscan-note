<script setup>
/**
 * 화면 0 — 로그인 / 회원가입 (api-spec.md 4절 화면 0)
 *
 * 흐름 3가지:
 *  1) 이메일 로그인      : POST /api/auth/login
 *  2) 이메일 회원가입    : 동의 폼 포함 -> POST /api/auth/signup
 *  3) SNS 간편가입/로그인: provider_token 으로 먼저 POST /api/auth/social-login (동의 없이) ->
 *                          백엔드가 400 CONSENT_REQUIRED 로 거부하면 = 신규 사용자 -> 동의 화면을 띄우고
 *                          consents 를 붙여 재요청. (기존 사용자는 첫 요청에서 바로 로그인)
 *     지금 SNS 인증 자체는 mock 이다: 실제 카카오/구글/네이버 SDK 대신 고정 provider_token 을 만들어 쓴다.
 *     실제 연동 시 provider_token 만 각 SDK 에서 받은 값으로 바꾸면 이 화면의 나머지 로직은 그대로 쓸 수 있다.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import ConsentForm from '../components/ConsentForm.vue'
import { getConsentVersion, login, resetPassword, signup, socialLogin, updateProfile } from '../api/endpoints'
import { applyAuthResult } from '../stores/auth'

const router = useRouter()
const route = useRoute()

/**
 * 로그아웃 요청이 서버에 닿지 못한 경우(네트워크 끊김 등) 안내한다.
 * 이 기기에서는 로그아웃됐지만 그 토큰은 서버에서 아직 유효하다 — 공용 PC 라면 중요한 정보다.
 */
const logoutIncomplete = computed(() => route.query.logout === 'local_only')

const mode = ref('login') // 'login' | 'signup'
const email = ref('')
const password = ref('')
const nickname = ref('')
/* 시안 02-2 의 프로필 항목. **닉네임만 필수이고 나머지는 선택이다** —
   없어도 학습에 아무 지장이 없으므로 가입을 막지 않는다. */
const birthDate = ref('')
const school = ref('')
const major = ref('')

/** 가입 2단계 (시안 02: 1 계정 정보 → 2 프로필·학교) */
const signupStep = ref(1)
/** 비밀번호 규칙은 서버와 같은 값을 쓴다 (backend/app/schemas.py) */
const MIN_PASSWORD_LENGTH = 8
const canGoToStep2 = computed(
  () => email.value.includes('@') && password.value.length >= MIN_PASSWORD_LENGTH,
)

const consentVersion = ref('')
const consentItems = ref([])
const consents = ref({})

const busy = ref(false)
const errorMessage = ref('')

// SNS 인증은 끝났지만 아직 동의를 안 받은 상태(= 신규 SNS 사용자)
const pendingSocial = ref(null)

const requiredKeys = computed(() => consentItems.value.filter((i) => i.required).map((i) => i.key))
const allRequiredChecked = computed(
  () => requiredKeys.value.length > 0 && requiredKeys.value.every((k) => consents.value[k] === true),
)

// 동의 폼을 보여줘야 하는 상황: 이메일 회원가입 중이거나, SNS 신규 가입 중
const showConsents = computed(() => mode.value === 'signup' || pendingSocial.value !== null)

onMounted(async () => {
  try {
    const data = await getConsentVersion()
    consentVersion.value = data.version
    consentItems.value = data.items
    // 모든 키를 false 로 초기화해야 백엔드 pydantic(bool 필수 필드)에서 튕기지 않는다.
    consents.value = Object.fromEntries(data.items.map((i) => [i.key, false]))
  } catch (e) {
    errorMessage.value = e.message
  }
})

function goNext(isNewUser = false) {
  // **홈으로 보낸다.** 이 줄은 홈 화면이 생기기 전 코드 그대로 `cases` 를 가리키고 있었다 —
  // 대시보드를 만들어 놓고 로그인은 거기로 보내지 않아, 들어오자마자 격자만 보였다.
  // (`redirect` 쿼리가 있으면 사용자가 원래 가려던 곳이 우선이다)
  if (route.query.redirect) {
    router.push(route.query.redirect)
    return
  }
  // 방금 가입한 사람만 기본정보 설정(시안 03)을 거친다. **건너뛸 수 있는 화면이다.**
  router.push({ name: isNewUser ? 'onboarding' : 'home' })
}

async function run(fn) {
  busy.value = true
  errorMessage.value = ''
  try {
    const result = await fn()
    applyAuthResult(result)
    // 서버가 신규 가입을 알려준다 (is_new_user). 로그인은 바로 홈으로 간다.
    goNext(result?.is_new_user === true)
  } catch (e) {
    errorMessage.value = e.message
  } finally {
    busy.value = false
  }
}

const onLogin = () => run(() => login({ email: email.value, password: password.value }))

function onSignup() {
  // 1단계에서는 아직 계정을 만들지 않는다 — 다음 단계로만 넘어간다
  if (signupStep.value === 1) {
    if (canGoToStep2.value) signupStep.value = 2
    return
  }
  return submitSignup()
}

const submitSignup = () =>
  run(async () => {
    const result = await signup({
      email: email.value,
      password: password.value,
      nickname: nickname.value,
      consents: consents.value,
    })
    // 가입이 끝난 뒤에 선택 항목을 저장한다. **실패해도 가입은 유효하다** —
    // 학교·전공 때문에 방금 만든 계정으로 못 들어가는 일은 없어야 한다.
    const optional = {}
    if (birthDate.value) optional.birth_date = birthDate.value
    if (school.value) optional.school = school.value
    if (major.value) optional.major = major.value
    if (Object.keys(optional).length) {
      applyAuthResult(result) // 토큰이 있어야 프로필을 저장할 수 있다
      await updateProfile(optional).catch(() => {})
    }
    return result
  })

/** mock SNS 인증: 실제 SDK 대신 provider 별 고정 토큰을 만들어 재사용한다(= 같은 계정으로 인식됨). */
function mockProviderToken(provider) {
  const key = 'mediscan.mock_social_token.' + provider
  let token = localStorage.getItem(key)
  if (!token) {
    token = 'mock-' + provider + '-' + Math.random().toString(36).slice(2, 10)
    localStorage.setItem(key, token)
  }
  return token
}

async function onSocial(provider) {
  busy.value = true
  errorMessage.value = ''
  const provider_token = mockProviderToken(provider)
  try {
    // 1차: 동의 없이 시도 — 이미 가입된 계정이면 여기서 바로 로그인된다.
    const result = await socialLogin({ provider, provider_token })
    applyAuthResult(result)
    goNext(result?.is_new_user === true)
  } catch (e) {
    if (e.code === 'CONSENT_REQUIRED') {
      // 신규 사용자 -> 동의 화면으로
      pendingSocial.value = { provider, provider_token }
      errorMessage.value = ''
    } else {
      errorMessage.value = e.message
    }
  } finally {
    busy.value = false
  }
}

const onSocialSignupComplete = () =>
  run(() =>
    socialLogin({
      provider: pendingSocial.value.provider,
      provider_token: pendingSocial.value.provider_token,
      consents: consents.value,
    }),
  )

function cancelSocial() {
  pendingSocial.value = null
  errorMessage.value = ''
}

/**
 * 비밀번호 재설정 — 운영자에게 받은 일회용 코드를 쓴다.
 *
 * 메일 발송 수단이 없어 "비밀번호 찾기" 메일을 보낼 수 없다. 그렇다고 재설정을 두지 않으면
 * 비밀번호를 잊은 사용자가 계정과 학습 이력을 영구히 잃는다.
 * 본인 확인은 운영자가 오프라인으로 한다.
 */
const reset = ref({ code: '', next: '', confirm: '' })
const resetDone = ref(false)

async function onReset() {
  if (reset.value.next !== reset.value.confirm) {
    errorMessage.value = '새 비밀번호가 서로 다릅니다.'
    return
  }
  busy.value = true
  errorMessage.value = ''
  try {
    await resetPassword({
      email: email.value,
      code: reset.value.code,
      new_password: reset.value.next,
    })
    resetDone.value = true
    reset.value = { code: '', next: '', confirm: '' }
    // 재설정 직후 토큰을 주지 않는다 — 새 비밀번호로 한 번 로그인하게 한다
    mode.value = 'login'
    password.value = ''
  } catch (e) {
    errorMessage.value = e.message
  } finally {
    busy.value = false
  }
}

function switchMode(next) {
  resetDone.value = false
  mode.value = next
  signupStep.value = 1 // 탭을 옮기면 가입 단계도 처음으로
  errorMessage.value = ''
}

const PROVIDERS = [
  { key: 'kakao', label: '카카오로 시작하기', short: '카카오' },
  { key: 'naver', label: '네이버로 시작하기', short: '네이버' },
  { key: 'google', label: 'Google로 시작하기', short: 'Google' },
]
</script>

<template>
  <div class="wrap">
    <!-- 시안 01 의 좌우 분할. 왼쪽은 브랜드 면, 오른쪽은 폼.
         **시안의 흉부 X-ray 배경은 쓰지 않는다** — 우리가 가진 영상은 실제 환자
         의료영상이고, 장식으로 쓸 성격이 아니다. 대신 격자·스캔선 모티프를 CSS 로 그린다. -->
    <div class="brand-side" aria-hidden="true">
      <div class="brand-grid"></div>
      <div class="brand-inner">
        <span class="mark">
          <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-4.2-4.2" stroke-linecap="round" />
            <path d="M11 8v6M8 11h6" stroke-linecap="round" />
          </svg>
        </span>
        <p class="brand-word">메디스캔<span>노트</span></p>
        <p class="brand-sub">의료영상 판독 학습</p>
      </div>
      <p class="brand-foot">교육 · 학습용 서비스</p>
    </div>

    <div class="form-side">
    <div class="hero">
      <h1>메디스캔노트</h1>
      <!-- **"AI 기준과 비교"는 사실이 아니었다.**
           채점 기준은 전문가가 검수한 reference mask 이고, AI 예측은
           참고 정보로만 나간다 (AI 가 못 찾은 케이스도 정상 채점된다).
           첫 화면 문구가 제품을 잘못 설명하면 학습자가 AI 를 정답으로 여기게 된다. -->
      <p class="lead">전문가가 검수한 기준과 비교하며 의료영상 판독을 연습하는 서비스</p>
    </div>

    <!-- 서버에 로그아웃이 닿지 못한 경우. 공용 PC 에서는 알아야 하는 정보다. -->
    <p v-if="logoutIncomplete" class="notice">
      이 기기에서는 로그아웃했지만 <strong>서버에 연결하지 못해 세션이 완전히 종료되지 않았습니다.</strong>
      공용 컴퓨터라면 네트워크 연결 후 다시 로그인해 로그아웃해 주세요.
    </p>

    <div class="card panel">
      <!-- SNS 신규 가입: 동의만 받는 단계 -->
      <template v-if="pendingSocial">
        <div class="step-head">
          <span class="badge">{{ pendingSocial.provider }}</span>
          <h2>간편가입 동의</h2>
        </div>
        <p class="lead">처음 오신 계정입니다. 아래 필수 항목에 동의하셔야 계정이 생성됩니다.</p>

        <ConsentForm v-model="consents" :items="consentItems" :version="consentVersion" :disabled="busy" />

        <p v-if="errorMessage" class="error">{{ errorMessage }}</p>

        <div class="actions">
          <button @click="cancelSocial" :disabled="busy">취소</button>
          <button class="primary lg grow" @click="onSocialSignupComplete" :disabled="busy || !allRequiredChecked">
            {{ busy ? '처리 중...' : '가입 완료' }}
          </button>
        </div>
      </template>

      <!-- 기본: SNS 버튼 + 이메일 로그인/가입 -->
      <template v-else>
        <div class="segmented full">
          <button :class="{ active: mode === 'login' }" @click="switchMode('login')">로그인</button>
          <button :class="{ active: mode === 'signup' }" @click="switchMode('signup')">회원가입</button>
          <button :class="{ active: mode === 'reset' }" @click="switchMode('reset')">비밀번호 재설정</button>
        </div>

        <p v-if="resetDone" class="notice ok">
          비밀번호를 재설정했습니다. 새 비밀번호로 로그인해 주세요.
        </p>

        <!-- 재설정: 운영자에게 받은 코드로 -->
        <form v-if="mode === 'reset'" @submit.prevent="onReset">
          <p class="reset-help">
            비밀번호를 잊으셨나요? <strong>운영자에게 재설정 코드를 요청</strong>한 뒤
            아래에 입력하세요. 코드는 발급 후 24시간 동안 한 번만 사용할 수 있습니다.
          </p>
          <label class="field">
            <span>이메일</span>
            <input v-model.trim="email" type="email" required autocomplete="email" />
          </label>
          <label class="field">
            <span>재설정 코드</span>
            <input v-model.trim="reset.code" type="text" required placeholder="XXXXX-XXXXX" />
          </label>
          <label class="field">
            <span>새 비밀번호 (8자 이상)</span>
            <input v-model="reset.next" type="password" required autocomplete="new-password" />
          </label>
          <label class="field">
            <span>새 비밀번호 확인</span>
            <input v-model="reset.confirm" type="password" required autocomplete="new-password" />
          </label>

          <p v-if="errorMessage" class="error">{{ errorMessage }}</p>

          <button class="primary lg full" type="submit" :disabled="busy">
            {{ busy ? '처리 중...' : '비밀번호 재설정' }}
          </button>
        </form>

        <form v-if="mode !== 'reset'" @submit.prevent="mode === 'login' ? onLogin() : onSignup()">
          <!-- 시안 02 의 2단계 가입 (1 계정 정보 / 2 프로필·학교).
               **동의는 시안에 없지만 반드시 받는다** — 2단계의 마지막,
               즉 계정이 실제로 만들어지는 버튼 바로 앞에 둔다. -->
          <ol v-if="mode === 'signup'" class="signup-steps" aria-label="가입 단계">
            <li :class="{ current: signupStep === 1, done: signupStep > 1 }">
              <span class="step-num">1</span> 계정 정보
            </li>
            <li :class="{ current: signupStep === 2 }">
              <span class="step-num">2</span> 프로필 · 학교
            </li>
          </ol>

          <template v-if="mode !== 'signup' || signupStep === 1">
            <label class="field">
              <span>이메일</span>
              <input v-model.trim="email" type="email" required autocomplete="email" placeholder="you@example.com" />
            </label>
            <label class="field">
              <span>비밀번호</span>
              <input
                v-model="password"
                type="password"
                required
                :autocomplete="mode === 'signup' ? 'new-password' : 'current-password'"
                placeholder="••••••••"
              />
            </label>
          </template>

          <!-- 2단계: 프로필 (시안 02-2). **닉네임만 필수이고 나머지는 선택이다** -->
          <template v-if="mode === 'signup' && signupStep === 2">
            <label class="field">
              <span>이름 (닉네임)</span>
              <input v-model.trim="nickname" type="text" required placeholder="화면에 표시될 이름" />
            </label>
            <label class="field">
              <span>생년월일 <small class="optional">선택</small></span>
              <input v-model="birthDate" type="date" />
            </label>
            <label class="field">
              <span>학교 <small class="optional">선택</small></span>
              <input v-model.trim="school" type="text" placeholder="예: 메드렌즈대학교" />
            </label>
            <label class="field">
              <span>전공 <small class="optional">선택</small></span>
              <input v-model.trim="major" type="text" placeholder="예: 방사선학과" />
            </label>
          </template>

          <ConsentForm
            v-if="showConsents && (mode !== 'signup' || signupStep === 2)"
            v-model="consents"
            :items="consentItems"
            :version="consentVersion"
            :disabled="busy"
          />

          <p v-if="errorMessage" class="error">{{ errorMessage }}</p>

          <div v-if="mode === 'signup' && signupStep === 2" class="step-actions">
            <button type="button" :disabled="busy" @click="signupStep = 1">이전</button>
            <button
              class="primary lg grow submit"
              type="submit"
              :disabled="busy || !allRequiredChecked"
            >
              {{ busy ? '처리 중...' : '가입 완료' }}
            </button>
          </div>
          <button
            v-else
            class="primary lg submit"
            type="submit"
            :disabled="busy || (mode === 'signup' && !canGoToStep2)"
          >
            {{ busy ? '처리 중...' : mode === 'login' ? '로그인' : '다음' }}
          </button>

          <p v-if="mode === 'signup' && signupStep === 2 && !allRequiredChecked" class="muted hint">
            필수 동의 {{ requiredKeys.length }}개를 모두 체크해야 가입할 수 있습니다.
          </p>
          <p v-else-if="mode === 'signup' && signupStep === 1" class="muted hint">
            이메일과 비밀번호({{ MIN_PASSWORD_LENGTH }}자 이상)를 입력하면 다음으로 넘어갑니다.
          </p>
          <p v-if="mode === 'login'" class="muted hint">
            가입한 계정과 판독 이력은 서버 DB에 저장됩니다. 로그인 상태는 7일간 유지됩니다.
          </p>
        </form>

        <!-- **동작하는 것을 먼저 둔다.** 예전에는 이 셋이 화면 맨 위에서 가장 큰 버튼이었고
             바로 아래에 "개발용 예시 로그인입니다"가 붙어 있었다 — 처음 온 사람이 가장 먼저
             보는 것이 **아직 안 되는 기능 세 개**였고, 정작 쓸 수 있는 이메일 로그인은
             스크롤해야 나왔다. 숨기지는 않는다(제품 범위는 보이는 편이 낫다).
             각 사에 앱을 등록해 실연동되면 다시 위로 올린다. -->
        <div class="or"><span>SNS 계정으로</span></div>

        <div class="social">
          <button
            v-for="p in PROVIDERS"
            :key="p.key"
            class="social-btn"
            :class="p.key"
            :disabled="busy"
            @click="onSocial(p.key)"
          >
            {{ p.label }}
          </button>
        </div>

        <p class="social-note">
          <strong>아직 연동 전입니다.</strong>
          카카오·구글·네이버 실제 인증을 붙이지 않아, 각 제공자별 임시 토큰으로 계정을
          만드는 개발용 예시 로그인입니다. 실제 SNS 계정 정보는 사용하지도 전송하지도 않습니다.
        </p>
      </template>
    </div>

    <p class="muted foot">의료영상(민감정보)을 다루는 서비스입니다. AI 분석 결과는 학습 참고용이며 확정 진단이 아닙니다.</p>
    </div>
  </div>
</template>

<style scoped>
/* --- 가입 단계 표시 (시안 02) --- */
.signup-steps {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  list-style: none;
  margin: 0 0 var(--sp-4);
  padding: 0;
}
.signup-steps li {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  padding: 7px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-full);
  color: var(--ink-muted);
  font-size: 12.5px;
  font-weight: 600;
}
/* **색만으로 끝난 단계를 표시하지 않는다** — 테두리·굵기도 함께 바뀐다 */
.signup-steps li.current,
.signup-steps li.done {
  border-color: var(--brand-500);
  background: var(--brand-50);
  color: var(--brand-700);
}
/* 선택 항목임을 라벨에 적는다 — 필수처럼 보이면 가입을 망설이게 된다 */
.optional {
  margin-left: 4px;
  padding: 1px 6px;
  border-radius: var(--r-full);
  background: var(--gray-100);
  color: var(--ink-muted);
  font-size: 10.5px;
  font-weight: 600;
}

.step-actions {
  display: flex;
  gap: var(--sp-3);
}
.step-actions .grow {
  flex: 1;
}

.step-num {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  flex: none;
  border-radius: var(--r-full);
  background: var(--gray-200);
  color: var(--ink-secondary);
  font-size: 11.5px;
}
.signup-steps li.current .step-num,
.signup-steps li.done .step-num {
  background: var(--brand-500);
  color: #fff;
}

.wrap {
  /* 시안 01: 왼쪽 브랜드 면 + 오른쪽 폼. 폼이 길어지는 화면(동의·재설정)도
     오른쪽 열에서만 늘어나므로 좌우가 어긋나지 않는다. */
  display: grid;
  grid-template-columns: 380px minmax(0, 460px);
  gap: 0;
  /* 폭을 내용에 맞춰야 배경(흰 면)이 빈 여백까지 번지지 않는다 */
  width: fit-content;
  max-width: 100%;
  margin: 0 auto;
  align-items: stretch;
  border-radius: var(--r-lg);
  overflow: hidden;
  box-shadow: var(--shadow-lg);
  background: var(--surface);
}

.brand-side {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: var(--sp-4);
  padding: var(--sp-12) var(--sp-8);
  background: linear-gradient(160deg, var(--navy-700), var(--navy-800));
  color: #fff;
  overflow: hidden;
}

/* 장식 — 스캔 격자. 실제 의료영상을 장식으로 쓰지 않기 위한 대체물이다. */
.brand-grid {
  position: absolute;
  inset: -10%;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.06) 1px, transparent 1px),
    radial-gradient(circle at 70% 65%, rgba(51, 167, 175, 0.28), transparent 55%);
  background-size: 26px 26px, 26px 26px, 100% 100%;
}

.brand-inner {
  position: relative;
}

.brand-word {
  margin: var(--sp-5) 0 4px;
  font-size: 32px;
  font-weight: 800;
  letter-spacing: -0.04em;
}
.brand-word span {
  color: var(--brand-400);
}
.brand-sub {
  margin: 0;
  color: rgba(255, 255, 255, 0.72);
  font-size: 14px;
  letter-spacing: 0.02em;
}
.brand-foot {
  position: relative;
  margin: 0;
  margin-top: auto;
  color: rgba(255, 255, 255, 0.5);
  font-size: 12px;
}

.form-side {
  padding: var(--sp-8);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  min-width: 0;
}

.hero {
  margin-bottom: 0;
}

.mark {
  display: inline-grid;
  place-items: center;
  width: 46px;
  height: 46px;
  border-radius: 13px;
  background: var(--brand-500);
  color: #fff;
}

.hero h1 {
  margin-bottom: 6px;
  font-size: 24px;
  color: var(--navy-700);
}

@media (max-width: 820px) {
  /* 좁은 화면에서는 브랜드 면을 위로 눕히고 높이를 줄인다 —
     폼이 화면 아래로 밀려나면 로그인부터 스크롤해야 한다. */
  .wrap {
    grid-template-columns: minmax(0, 460px);
    width: auto;
  }
  .brand-side {
    padding: var(--sp-6);
  }
  .brand-word {
    margin-top: var(--sp-3);
    font-size: 26px;
  }
  .brand-foot {
    display: none;
  }
}

.panel {
  /* 좌우 분할 카드 안이라 카드를 한 겹 더 얹지 않는다 (테두리·그림자 중복) */
  padding: 0;
  border: 0;
  background: none;
  box-shadow: none;
}

.step-head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-bottom: 6px;
}

.reset-help {
  margin: 0 0 var(--sp-3);
  font-size: 12.5px;
  line-height: 1.6;
  color: var(--ink-secondary);
}

.social-note {
  margin: var(--sp-3) 0 0;
  padding: var(--sp-3);
  border-radius: var(--r-sm);
  background: var(--surface-sunken);
  border: 1px dashed var(--line-strong);
  color: var(--ink-secondary);
  font-size: 12.5px;
  line-height: 1.6;
}

.social {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.social-btn {
  width: 100%;
  font-weight: 600;
}

/* 각 제공사 브랜드 색 */
.social-btn.kakao {
  background: #fee500;
  border-color: #f2da00;
  color: #191600;
}

.social-btn.kakao:hover:not(:disabled) {
  background: #f7dd00;
  border-color: #e6cf00;
}

.social-btn.naver {
  background: #03c75a;
  border-color: #02b351;
  color: #fff;
}

.social-btn.naver:hover:not(:disabled) {
  background: #02b351;
  border-color: #029c47;
}

.social-btn.google {
  background: #fff;
  border-color: var(--line-strong);
  color: var(--gray-800);
}

.or {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin: var(--sp-5) 0 var(--sp-4);
  color: var(--ink-muted);
  font-size: 12.5px;
}

.or::before,
.or::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--line);
}

.segmented.full {
  display: flex;
  width: 100%;
  margin-bottom: var(--sp-4);
}

.segmented.full button {
  flex: 1;
}

.submit {
  width: 100%;
  margin-top: var(--sp-4);
}

.actions {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-4);
}

.actions .grow {
  flex: 1;
}

.hint {
  margin-top: var(--sp-2);
}

.foot {
  margin-top: var(--sp-5);
  text-align: center;
  font-size: 12px;
  line-height: 1.7;
}
</style>
