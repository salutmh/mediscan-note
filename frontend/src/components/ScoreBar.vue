<script setup>
/**
 * 0~100 값을 가로 막대로. 숫자 옆에 붙여 **크기 감각**을 준다.
 *
 * 색만으로 뜻을 전달하지 않는다 — 항상 숫자가 함께 있어야 한다
 * (색각 이상 사용자에게 막대만 남으면 아무 정보가 아니다).
 * 그래서 이 컴포넌트는 `aria-hidden` 이고, 접근성 정보는 옆의 텍스트가 담당한다.
 */
const props = defineProps({
  value: { type: Number, default: 0 },
  /** match | partial_match | mismatch | neutral */
  tone: { type: String, default: 'neutral' },
})

const clamped = () => Math.max(0, Math.min(100, Math.round(props.value || 0)))
</script>

<template>
  <div class="bar" :data-tone="tone" aria-hidden="true">
    <span class="fill" :style="{ width: clamped() + '%' }" />
  </div>
</template>

<style scoped>
.bar {
  height: 6px;
  border-radius: var(--r-full);
  background: var(--gray-100);
  overflow: hidden;
}
.fill {
  display: block;
  height: 100%;
  border-radius: var(--r-full);
  background: var(--gray-400);
  transition: width 0.35s ease;
}
.bar[data-tone='match'] .fill {
  background: var(--mark-match);
}
.bar[data-tone='partial_match'] .fill {
  background: var(--mark-partial);
}
.bar[data-tone='mismatch'] .fill {
  background: var(--mark-mismatch);
}
.bar[data-tone='brand'] .fill {
  background: var(--accent);
}
</style>
