<script setup>
defineProps({
  cases: {
    type: Array,
    default: () => [],
  },
  selectedCaseId: {
    type: String,
    default: '',
  },
})

const emit = defineEmits(['select'])
</script>

<template>
  <aside class="case-list">
    <div class="case-list__header">
      <h2>AI 학습 케이스</h2>
      <span>{{ cases.length }}건</span>
    </div>

    <button
      v-for="item in cases"
      :key="item.case_id"
      class="case-card"
      :class="{ active: item.case_id === selectedCaseId }"
      type="button"
      @click="emit('select', item.case_id)"
    >
      <div class="case-card__title">{{ item.case_id }}</div>

      <div class="case-card__meta">
        <span>{{ item.source_disease }}</span>
        <span>AI {{ item.prediction_count }}개</span>
      </div>
    </button>
  </aside>
</template>

<style scoped>
.case-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.case-list__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.case-list__header h2 {
  margin: 0;
  font-size: 18px;
}

.case-list__header span {
  font-size: 13px;
  opacity: 0.65;
}

.case-card {
  width: 100%;
  padding: 14px;
  border: 1px solid #ddd;
  border-radius: 12px;
  background: #fff;
  text-align: left;
  cursor: pointer;
}

.case-card.active {
  border-color: #222;
}

.case-card__title {
  font-weight: 700;
  word-break: break-all;
}

.case-card__meta {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: 8px;
  font-size: 12px;
  opacity: 0.7;
}
</style>
