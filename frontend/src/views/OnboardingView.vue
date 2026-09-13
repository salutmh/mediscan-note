<script setup>
/**
 * 기본정보 설정 (시안 03) — 가입 직후 직군을 고른다.
 *
 * **건너뛸 수 있다.** 직군은 학습자 배경일 뿐이고, 비어 있어도 모든 기능이 그대로
 * 동작한다. 여기서 막으면 서비스를 보기도 전에 개인정보부터 내라는 화면이 된다.
 * 시안에는 건너뛰기가 없지만 넣었다.
 *
 * **의료 자격을 확인하는 화면이 아니다.** 고른 직군으로 무엇을 잠그거나 열지 않는다 —
 * 이 서비스는 교육용이고, 여기서 "의료인 인증"을 흉내 내면 그게 더 위험하다.
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { updateProfile } from '../api/endpoints'

const router = useRouter()

/**
 * 시안 03 의 네 가지. 코드는 영문으로 저장하고 화면 문구만 한국어로 둔다
 * (다국어·통계 집계를 생각하면 표시 문자열을 그대로 저장하지 않는 편이 낫다).
 */
const ROLES = [
  {
    code: 'medical_student',
    label: '의대생',
    paths: ['M12 4a3 3 0 0 1 3 3v1H9V7a3 3 0 0 1 3-3z', 'M5 20v-3a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v3'],
  },
  {
    code: 'radiology_student',
    label: '방사선학과 학생',
    paths: ['M12 4v16', 'M7 6c0 6-1 8-3 9 0-5 .5-7 1-9z', 'M17 6c0 6 1 8 3 9 0-5-.5-7-1-9z'],
  },
  {
    code: 'radiology_resident',
    label: '영상의학과 학생',
    paths: ['M4 5h16v11H4z', 'M9 20h6', 'M12 16v4', 'M8 10.5l2.5 2.5L16 8'],
  },
  {
    code: 'nursing_student',
    label: '간호대생',
    paths: ['M12 4a3 3 0 0 1 3 3v1H9V7a3 3 0 0 1 3-3z', 'M5 20v-3a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v3', 'M12 15v4M10 17h4'],
  },
]

const selected = ref('')
const busy = ref(false)
const errorMessage = ref('')

async function finish(skip = false) {
  busy.value = true
  errorMessage.value = ''
  try {
    // 건너뛰면 아무것도 저장하지 않는다 (빈 값을 굳이 쓰지 않는다)
    if (!skip && selected.value) await updateProfile({ job_role: selected.value })
    router.push({ name: 'home' })
  } catch (e) {
    // 프로필 저장은 **학습을 막을 이유가 아니다.** 실패해도 들어갈 수 있게 한다.
    errorMessage.value = '저장하지 못했습니다. 나중에 계정 설정에서 다시 고를 수 있습니다.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <section class="onboarding">
    <div class="card panel">
      <h1>기본정보 설정</h1>

      <section class="block">
        <h2>직군 선택</h2>
        <p class="muted">해당하는 직군을 선택해주세요. 나중에 바꿀 수 있습니다.</p>

        <ul class="role-grid">
          <li v-for="r in ROLES" :key="r.code">
            <button
              class="role"
              :class="{ active: selected === r.code }"
              :aria-pressed="selected === r.code"
              @click="selected = selected === r.code ? '' : r.code"
            >
              <span class="role-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
                  <path v-for="(d, i) in r.paths" :key="i" :d="d" />
                </svg>
              </span>
              <span class="role-label">{{ r.label }}</span>
              <!-- 고른 것을 **체크 표시로도** 알린다 (색만으로 구분하지 않는다) -->
              <span v-if="selected === r.code" class="role-check" aria-hidden="true">✓</span>
            </button>
          </li>
        </ul>
      </section>

      <p v-if="errorMessage" class="error">{{ errorMessage }}</p>

      <button class="primary lg wide" :disabled="busy" @click="finish(false)">
        {{ busy ? '저장 중…' : '시작하기' }}
      </button>
      <button class="ghost wide skip" :disabled="busy" @click="finish(true)">
        나중에 하기
      </button>

      <p class="muted note">
        직군은 <strong>학습자 배경</strong>일 뿐입니다. 고르지 않아도 모든 기능을 그대로
        쓸 수 있고, 이 선택으로 잠기거나 열리는 기능은 없습니다.
      </p>
    </div>
  </section>
</template>

<style scoped>
.onboarding {
  display: flex;
  justify-content: center;
}
.panel {
  width: 100%;
  max-width: 560px;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding: var(--sp-8);
}

h1 {
  margin: 0 auto var(--sp-2);
  padding-bottom: var(--sp-3);
  font-size: 26px;
  color: var(--navy-700);
  /* 시안은 제목 아래에 짧은 teal 밑줄을 둔다 */
  border-bottom: 3px solid var(--brand-500);
}

.block h2 {
  margin: 0 0 2px;
  font-size: 14px;
  color: var(--navy-700);
}
.block .muted {
  margin: 0 0 var(--sp-4);
  font-size: 12.5px;
}

.role-grid {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--sp-3);
}
.role {
  position: relative;
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--sp-2);
  min-height: 118px;
  padding: var(--sp-5) var(--sp-3);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
}
.role:hover:not(:disabled) {
  border-color: var(--brand-300);
}
.role.active {
  border-color: var(--brand-500);
  background: var(--brand-50);
}
.role-icon {
  display: grid;
  place-items: center;
  width: 52px;
  height: 52px;
  border-radius: var(--r-full);
  background: var(--brand-50);
  color: var(--brand-600);
}
.role.active .role-icon {
  background: #fff;
}
.role-icon svg {
  width: 28px;
  height: 28px;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.role-label {
  font-size: 13.5px;
  font-weight: 700;
  color: var(--navy-700);
}
.role-check {
  position: absolute;
  top: 10px;
  right: 10px;
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border-radius: var(--r-full);
  background: var(--brand-500);
  color: #fff;
  font-size: 12px;
}

.skip {
  justify-content: center;
}

.note {
  margin: var(--sp-2) 0 0;
  font-size: 12px;
  line-height: 1.7;
  text-align: center;
}
</style>
