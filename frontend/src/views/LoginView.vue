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
import { getConsentVersion, login, resetPassword, signup, socialLogin } from '../api/endpoints'
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

function goNext() {
  router.push(route.query.redirect || { name: 'cases' })
}

async function run(fn) {
  busy.value = true
  errorMessage.value = ''
  try {
    const result = await fn()
    applyAuthResult(result)
    goNext()
  } catch (e) {
    errorMessage.value = e.message
  } finally {
    busy.value = false
  }
}

const onLogin = () => run(() => login({ email: email.value, password: password.value }))

const onSignup = () =>
  run(() =>
    signup({
      email: email.value,
      password: password.value,
      nickname: nickname.value,
      consents: consents.value,
    }),
  )

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
    goNext()
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
    <div class="hero">
      <span class="mark" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="11" cy="11" r="7" />
          <path d="M20 20l-4.2-4.2" stroke-linecap="round" />
          <path d="M11 8v6M8 11h6" stroke-linecap="round" />
        </svg>
      </span>
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
        <div class="social">
          <button
            v-for="p in PROVIDERS"
            :key="p.key"
            class="lg social-btn"
            :class="p.key"
            :disabled="busy"
            @click="onSocial(p.key)"
          >
            {{ p.label }}
          </button>
        </div>

        <p class="social-note">
          <strong>개발용 예시 로그인입니다.</strong>
          아직 카카오·구글·네이버 실제 인증을 연동하지 않아, 각 제공자별 임시 토큰으로
          계정을 만듭니다. 실제 SNS 계정 정보는 사용하지도 전송하지도 않습니다.
        </p>

        <div class="or"><span>또는 이메일로</span></div>

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
          <label class="field">
            <span>이메일</span>
            <input v-model.trim="email" type="email" required autocomplete="email" placeholder="you@example.com" />
          </label>
          <label class="field">
            <span>비밀번호</span>
            <input v-model="password" type="password" required autocomplete="current-password" placeholder="••••••••" />
          </label>
          <label v-if="mode === 'signup'" class="field">
            <span>닉네임</span>
            <input v-model.trim="nickname" type="text" required placeholder="화면에 표시될 이름" />
          </label>

          <ConsentForm
            v-if="showConsents"
            v-model="consents"
            :items="consentItems"
            :version="consentVersion"
            :disabled="busy"
          />

          <p v-if="errorMessage" class="error">{{ errorMessage }}</p>

          <button
            class="primary lg submit"
            type="submit"
            :disabled="busy || (mode === 'signup' && !allRequiredChecked)"
          >
            {{ busy ? '처리 중...' : mode === 'login' ? '로그인' : '가입 완료' }}
          </button>

          <p v-if="mode === 'signup' && !allRequiredChecked" class="muted hint">
            필수 동의 {{ requiredKeys.length }}개를 모두 체크해야 가입할 수 있습니다.
          </p>
          <p v-if="mode === 'login'" class="muted hint">
            가입한 계정과 판독 이력은 서버 DB에 저장됩니다. 로그인 상태는 7일간 유지됩니다.
          </p>
        </form>
      </template>
    </div>

    <p class="muted foot">의료영상(민감정보)을 다루는 서비스입니다. AI 분석 결과는 학습 참고용이며 확정 진단이 아닙니다.</p>
  </div>
</template>

<style scoped>
.wrap {
  max-width: 420px;
  margin: 0 auto;
}

.hero {
  text-align: center;
  margin-bottom: var(--sp-6);
}

.mark {
  display: inline-grid;
  place-items: center;
  width: 46px;
  height: 46px;
  margin-bottom: var(--sp-3);
  border-radius: 13px;
  background: var(--brand-500);
  color: #fff;
  box-shadow: var(--shadow-md);
}

.hero h1 {
  margin-bottom: 6px;
}

.panel {
  padding: var(--sp-6);
  box-shadow: var(--shadow-lg);
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
