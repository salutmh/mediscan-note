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
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { deleteAccount } from '../api/endpoints'
import { authState, logout } from '../stores/auth'

const router = useRouter()

const confirming = ref(false)
const password = ref('')
const busy = ref(false)
const error = ref('')
const result = ref(null)

// SNS 가입자는 비밀번호가 없다 (서버도 이 경우 비밀번호를 요구하지 않는다)
const isEmailAccount = computed(() => Boolean(authState.user?.email))

const DELETED_LABEL = {
  consents: '동의 이력',
  submissions: '제출·채점 이력',
  learning_events: '학습 기록',
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
    // 계정이 사라졌으므로 토큰도 더는 쓸 수 없다 (서버가 401 을 준다)
    logout()
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
      <div class="card">
        <h2>내 정보</h2>
        <dl class="rows">
          <div><dt>닉네임</dt><dd>{{ authState.user?.nickname ?? '-' }}</dd></div>
          <div>
            <dt>{{ isEmailAccount ? '이메일' : '로그인 방식' }}</dt>
            <dd>{{ authState.user?.email ?? '간편 로그인 (개발용 예시)' }}</dd>
          </div>
        </dl>
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

.card.done ul {
  padding-left: 18px;
  font-size: 13.5px;
  line-height: 1.7;
}
</style>
