import { createRouter, createWebHistory } from 'vue-router'
import { authState } from '../stores/auth'

const routes = [
  { path: '/', redirect: '/cases' },
  // 화면 0
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
  // 화면 1
  { path: '/cases', name: 'cases', component: () => import('../views/CaseListView.vue'), meta: { requiresAuth: true } },
  // 화면 2 (+ 제출 후 화면 3·4)
  {
    path: '/cases/:caseId',
    name: 'reading',
    component: () => import('../views/ReadingView.vue'),
    meta: { requiresAuth: true },
  },
  // 화면 6
  {
    path: '/wrong-notes',
    name: 'wrong-notes',
    component: () => import('../views/WrongNotesView.vue'),
    meta: { requiresAuth: true },
  },
  // 화면 6의 재도전 — 판독 훈련 화면을 재사용하고, 제출만 retry 엔드포인트로 보낸다
  {
    path: '/wrong-notes/:caseId/retry',
    name: 'retry',
    component: () => import('../views/ReadingView.vue'),
    meta: { requiresAuth: true, retry: true },
  },
  // 화면 5
  {
    path: '/analyze',
    name: 'analyze',
    component: () => import('../views/AnalyzeView.vue'),
    meta: { requiresAuth: true },
  },
  // 화면 7
  {
    path: '/progress',
    name: 'progress',
    component: () => import('../views/MyProgressView.vue'),
    meta: { requiresAuth: true },
  },
]

export const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 나머지 API 가 전부 Bearer 토큰을 요구하므로, 토큰 없으면 화면 0으로 보낸다.
router.beforeEach((to) => {
  if (to.meta.requiresAuth && !authState.token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (to.name === 'login' && authState.token) {
    return { name: 'cases' }
  }
  return true
})
