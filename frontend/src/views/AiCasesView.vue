<script setup>
import { onMounted, ref } from 'vue'
import AiCaseList from '../components/AiCaseList.vue'
import AiCaseDetail from '../components/AiCaseDetail.vue'
import { getAiCase, getAiCases } from '../api/medicalAiApi'

const cases = ref([])
const selectedCaseId = ref('')
const selectedCase = ref(null)
const loading = ref(false)
const error = ref('')

async function loadCases() {
  loading.value = true
  error.value = ''

  try {
    const data = await getAiCases()
    cases.value = data.cases || []

    if (cases.value.length) {
      await selectCase(cases.value[0].case_id)
    }
  } catch (e) {
    error.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

async function selectCase(caseId) {
  selectedCaseId.value = caseId
  error.value = ''

  try {
    selectedCase.value = await getAiCase(caseId)
  } catch (e) {
    error.value = e.message || String(e)
  }
}

onMounted(loadCases)
</script>

<template>
  <main class="page">
    <div v-if="loading" class="status">불러오는 중...</div>
    <div v-else-if="error" class="status error">{{ error }}</div>

    <div v-else class="layout">
      <AiCaseList
        :cases="cases"
        :selected-case-id="selectedCaseId"
        @select="selectCase"
      />

      <AiCaseDetail :case-data="selectedCase" />
    </div>
  </main>
</template>

<style scoped>
.page {
  width: min(1400px, calc(100% - 32px));
  margin: 0 auto;
  padding: 28px 0;
}

.layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 28px;
  align-items: start;
}

.status {
  padding: 20px;
}

.error {
  color: #b42318;
}

@media (max-width: 900px) {
  .layout {
    grid-template-columns: 1fr;
  }
}
</style>
