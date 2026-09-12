<script setup>
/**
 * 의학용어 사전 (시안 07 우측 패널).
 *
 * **여기 나오는 설명은 전부 서버가 준 문헌 콘텐츠 그대로다.**
 * 프론트에서 용어를 만들거나 설명을 덧붙이지 않는다. 콘텐츠가 없는 질환은
 * 빈 목록이 오고, 그때는 "준비된 용어가 없습니다"라고 쓴다 —
 * 그럴듯한 설명을 지어내는 것보다 비어 있는 편이 낫다.
 *
 * 시안에는 발음 듣기(스피커) 아이콘이 있지만 넣지 않았다.
 * 한국어 TTS 로 영문 의학용어를 읽히면 틀린 발음을 가르치게 된다.
 */
import { computed, ref, watch } from 'vue'
import { getGlossary } from '../api/endpoints'

const props = defineProps({
  disease: { type: String, default: null },
  diseaseLabel: { type: String, default: '' },
})
defineEmits(['close'])

const terms = ref([])
const loading = ref(false)
const errorMessage = ref('')
const query = ref('')
const openIndex = ref(-1)

async function load() {
  if (!props.disease) {
    terms.value = []
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    const data = await getGlossary(props.disease)
    terms.value = data.terms ?? []
  } catch (e) {
    // 사전은 **부가 기능**이다. 실패해도 판독은 계속할 수 있어야 한다.
    errorMessage.value = '용어를 불러오지 못했습니다. 판독과 제출은 그대로 진행할 수 있습니다.'
    terms.value = []
  } finally {
    loading.value = false
  }
}

watch(() => props.disease, load, { immediate: true })

const visible = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return terms.value
  return terms.value.filter(
    (t) =>
      t.term.toLowerCase().includes(q) || (t.description ?? '').toLowerCase().includes(q),
  )
})

/**
 * "소뇌교각 (cerebellopontine angle, CPA)" 처럼 한 줄에 한글·영문이 함께 온다.
 * 시안은 영문을 제목, 한글을 부제로 쓴다. **괄호를 기준으로 나눠 보여주기만 하고,
 * 없으면 원문 그대로 둔다** (없는 번역을 만들지 않는다).
 */
function splitTerm(raw) {
  const m = /^(.*?)\s*\(([^)]+)\)\s*$/.exec(raw ?? '')
  if (!m) return { title: raw, sub: '' }
  return { title: m[2], sub: m[1] }
}
</script>

<template>
  <aside class="glossary card">
    <header class="g-head">
      <h2>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true">
          <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H11v16H5.5A1.5 1.5 0 0 1 4 18.5z" />
          <path d="M20 5.5A1.5 1.5 0 0 0 18.5 4H13v16h5.5a1.5 1.5 0 0 0 1.5-1.5z" />
        </svg>
        의학용어 사전
      </h2>
      <button class="ghost sm g-close" aria-label="사전 닫기" @click="$emit('close')">✕</button>
    </header>

    <label class="g-search">
      <span class="sr-only">용어 검색</span>
      <input v-model="query" type="search" placeholder="용어를 입력하세요" />
    </label>

    <p v-if="diseaseLabel" class="g-scope">
      <span class="chip-tag">{{ diseaseLabel }}</span>
      <span class="muted">문헌 기반 용어</span>
    </p>

    <p v-if="loading" class="g-note muted">불러오는 중…</p>
    <p v-else-if="errorMessage" class="g-note error">{{ errorMessage }}</p>
    <p v-else-if="!terms.length" class="g-note muted">
      이 질환은 아직 준비된 용어가 없습니다.
    </p>
    <p v-else-if="!visible.length" class="g-note muted">검색 결과가 없습니다.</p>

    <ul v-else class="g-list">
      <li v-for="(t, i) in visible" :key="t.term">
        <button
          class="g-item"
          :class="{ open: openIndex === i }"
          :aria-expanded="openIndex === i"
          @click="openIndex = openIndex === i ? -1 : i"
        >
          <span class="g-term">
            <strong>{{ splitTerm(t.term).title }}</strong>
            <small v-if="splitTerm(t.term).sub">{{ splitTerm(t.term).sub }}</small>
          </span>
          <span class="g-caret" aria-hidden="true">›</span>
        </button>
        <p v-if="openIndex === i" class="g-desc">{{ t.description }}</p>
      </li>
    </ul>

    <p class="g-foot muted">
      질환 일반 문헌 정보입니다. 이 케이스의 소견이 아닙니다.
    </p>
  </aside>
</template>

<style scoped>
.glossary {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-4);
}

.g-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
}
.g-head h2 {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: 15px;
  color: var(--navy-700);
}
.g-head svg {
  width: 17px;
  height: 17px;
  color: var(--brand-600);
  stroke-linecap: round;
  stroke-linejoin: round;
}
.g-close {
  min-width: 32px;
  min-height: 32px;
  padding: 2px 8px;
}

.g-search input {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--surface);
  font: inherit;
}
.g-search input:focus-visible {
  outline: 2px solid var(--brand-300);
  outline-offset: 1px;
}

.g-scope {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin: 0;
  font-size: 12px;
}
.chip-tag {
  padding: 3px 10px;
  border-radius: var(--r-full);
  background: var(--brand-50);
  color: var(--brand-700);
  font-weight: 700;
}

.g-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  /* 용어가 늘어나도 판독 화면 높이를 밀어내지 않게 */
  max-height: 420px;
  overflow-y: auto;
}

.g-item {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  padding: 10px 12px;
  text-align: left;
  border-radius: var(--r-sm);
  border-color: var(--line);
  background: var(--gray-25);
}
.g-item:hover:not(:disabled) {
  border-color: var(--brand-300);
  background: var(--surface);
}
.g-item.open {
  border-color: var(--brand-500);
  background: var(--brand-50);
}
.g-term {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.g-term strong {
  color: var(--navy-700);
  font-size: 13.5px;
  white-space: normal;
}
.g-term small {
  color: var(--brand-700);
  font-size: 11.5px;
}
.g-caret {
  color: var(--gray-400);
  font-size: 17px;
  line-height: 1;
}

.g-desc {
  margin: var(--sp-2) 2px 0;
  padding: 0 10px 2px;
  font-size: 12.5px;
  line-height: 1.65;
  color: var(--ink-secondary);
}

.g-note {
  margin: var(--sp-3) 0;
  font-size: 12.5px;
  text-align: center;
}

.g-foot {
  margin: 0;
  padding-top: var(--sp-2);
  border-top: 1px solid var(--line);
  font-size: 11.5px;
}
</style>
