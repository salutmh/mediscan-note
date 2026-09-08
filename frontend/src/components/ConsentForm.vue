<script setup>
/**
 * 화면 0의 동의 영역.
 * 항목·문구·필수여부는 하드코딩하지 않고 GET /api/consents/current-version 응답(items)을 그대로 렌더링한다.
 * 약관이 바뀌어도 프론트를 고칠 필요가 없고, 어떤 버전에 동의했는지도 화면에 남는다 (api-spec.md 1절).
 */
import { computed } from 'vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  version: { type: String, default: '' },
  modelValue: { type: Object, required: true },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const allChecked = computed(() => props.items.length > 0 && props.items.every((i) => props.modelValue[i.key]))

const requiredDone = computed(() => {
  const required = props.items.filter((i) => i.required)
  return required.length > 0 && required.every((i) => props.modelValue[i.key])
})

const requiredCount = computed(() => props.items.filter((i) => i.required).length)
const requiredChecked = computed(
  () => props.items.filter((i) => i.required && props.modelValue[i.key]).length,
)

/**
 * change 이벤트의 `target.checked` (= 브라우저가 방금 만든 새 상태)를 그대로 받는다.
 * props.modelValue 에서 다음 값을 계산하면 연속 클릭 때 아직 반영 안 된 값(stale props)을
 * 뒤집게 되므로 쓰지 않는다.
 */
function toggle(key, checked) {
  emit('update:modelValue', { ...props.modelValue, [key]: checked })
}

function toggleAll(checked) {
  const next = { ...props.modelValue }
  for (const item of props.items) next[item.key] = checked
  emit('update:modelValue', next)
}
</script>

<template>
  <fieldset class="consents" :disabled="disabled">
    <legend class="sr-only">약관 동의</legend>

    <div class="head">
      <span class="title">약관 동의</span>
      <span class="progress" :class="{ done: requiredDone }">
        필수 {{ requiredChecked }}/{{ requiredCount }}
      </span>
      <span v-if="version" class="ver">v{{ version }}</span>
    </div>

    <!--
      체크 상태는 modelValue 가 유일한 기준이고(:checked), 변경은 change 이벤트의
      target.checked 로 받는다.

      ⚠️ input 에 @click.prevent 를 쓰면 안 된다. input 이 label 안에 있으면 클릭이 label 로
      버블링되고, label 의 기본 동작이 자기 control 에 클릭을 **한 번 더** 보낸다.
      그래서 핸들러가 두 번 돌아 서로 상쇄되고, 화면에서는 "클릭해도 아무 반응이 없는" 것처럼 보였다.
      change 는 실제 상태가 바뀔 때만 한 번 발생하므로 이 문제가 없다.
    -->
    <label class="row all">
      <input type="checkbox" :checked="allChecked" @change="toggleAll($event.target.checked)" />
      <span class="all-text">전체 동의 <span class="muted">(선택 항목 포함)</span></span>
    </label>

    <label v-for="item in items" :key="item.key" class="row">
      <input
        type="checkbox"
        :checked="!!modelValue[item.key]"
        @change="toggle(item.key, $event.target.checked)"
      />
      <span class="text">
        <span class="tag" :class="item.required ? 'req' : 'opt'">{{ item.required ? '필수' : '선택' }}</span>
        <span class="label-text">{{ item.title }}</span>
        <a v-if="item.url" :href="item.url" target="_blank" rel="noopener" class="view">보기</a>
      </span>
    </label>

    <p v-if="!items.length" class="muted empty">동의 항목을 불러오지 못했습니다.</p>
  </fieldset>
</template>

<style scoped>
.consents {
  margin: var(--sp-4) 0 0;
  padding: var(--sp-4);
  border: 1px solid var(--line);
  border-radius: var(--r-md);
  background: var(--gray-25);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}

.head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-bottom: var(--sp-2);
}

.title {
  font-size: 13.5px;
  font-weight: 600;
}

.progress {
  padding: 2px 8px;
  border-radius: var(--r-full);
  background: var(--gray-100);
  color: var(--ink-muted);
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0;
  font-variant-numeric: tabular-nums;
}

.progress.done {
  background: var(--match-bg);
  color: var(--match-ink);
}

.ver {
  margin-left: auto;
  color: var(--gray-400);
  font-size: 11.5px;
}

.row {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
  padding: 6px 0;
  font-size: 13.5px;
  line-height: 1.5;
  cursor: pointer;
}

.row input[type='checkbox'] {
  margin-top: 2px;
}

.row.all {
  padding: 8px 10px;
  margin: 0 -10px var(--sp-1);
  border-radius: var(--r-sm);
  background: var(--surface);
  border: 1px solid var(--line);
}

.all-text {
  font-weight: 600;
  font-size: 14px;
}

.all-text .muted {
  font-weight: 400;
  font-size: 12.5px;
}

/* flex + wrap 으로 두면 긴 문구(AI 고지 등)가 통째로 다음 줄로 내려가 태그만 남는다.
   일반 인라인 흐름으로 두면 태그 옆에서 자연스럽게 줄바꿈된다. */
.text {
  display: block;
}

.tag {
  display: inline-block;
  margin-right: 5px;
  padding: 1px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0;
  white-space: nowrap;
}

.tag.req {
  background: var(--mismatch-bg);
  color: var(--mismatch-ink);
}

.tag.opt {
  background: var(--gray-100);
  color: var(--ink-muted);
}

.label-text {
  color: var(--ink-secondary);
}

.view {
  margin-left: 5px;
  font-size: 12px;
  color: var(--ink-muted);
  text-decoration: underline;
}

.view:hover {
  color: var(--brand-600);
}

.empty {
  margin-top: var(--sp-2);
}
</style>
