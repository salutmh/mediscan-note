<script setup>
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import { authState, isLoggedIn, logout } from './stores/auth'

const router = useRouter()
const route = useRoute()

function onLogout() {
  logout()
  router.push({ name: 'login' })
}

const NAV = [
  { name: 'cases', label: '케이스', prefix: '/cases' },
  { name: 'wrong-notes', label: '복습노트', prefix: '/wrong-notes' },
  { name: 'analyze', label: '내 영상 분석', prefix: '/analyze' },
  { name: 'progress', label: '진행현황', prefix: '/progress' },
]

/**
 * 상세 화면(/cases/:id, /wrong-notes/:id/retry)은 목록과 별도 라우트라
 * router-link-active 가 안 붙는다. 경로 접두사로 직접 판단해서
 * 판독 중에도 지금 어느 메뉴에 있는지 보이게 한다.
 */
function isActive(item) {
  return route.path === item.prefix || route.path.startsWith(item.prefix + '/')
}

/** 닉네임 첫 글자로 만드는 아바타 */
function initial(nickname) {
  return (nickname ?? '?').trim().charAt(0) || '?'
}
</script>

<template>
  <header class="topbar">
    <div class="topbar-inner">
      <RouterLink to="/cases" class="brand">
        <span class="mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="11" cy="11" r="7" />
            <path d="M20 20l-4.2-4.2" stroke-linecap="round" />
            <path d="M11 8v6M8 11h6" stroke-linecap="round" />
          </svg>
        </span>
        <span class="brand-name">메디스캔노트</span>
      </RouterLink>

      <nav v-if="isLoggedIn" class="nav">
        <RouterLink
          v-for="item in NAV"
          :key="item.name"
          :to="{ name: item.name }"
          class="nav-link"
          :class="{ current: isActive(item) }"
        >
          {{ item.label }}
        </RouterLink>
      </nav>

      <div v-if="isLoggedIn" class="account">
        <span class="avatar" aria-hidden="true">{{ initial(authState.user?.nickname) }}</span>
        <span class="nickname">{{ authState.user?.nickname ?? '사용자' }}</span>
        <button class="ghost sm" @click="onLogout">로그아웃</button>
      </div>
    </div>
  </header>

  <main class="page">
    <RouterView />
  </main>
</template>

<style scoped>
.topbar {
  position: sticky;
  top: 0;
  z-index: 20;
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--line);
}

.topbar-inner {
  max-width: 1080px;
  margin: 0 auto;
  display: flex;
  align-items: center;
  gap: var(--sp-6);
  padding: 11px var(--sp-5);
}

.brand {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  text-decoration: none;
  color: var(--ink);
  flex: 0 0 auto;
}

.mark {
  display: grid;
  place-items: center;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  background: var(--brand-500);
  color: #fff;
}

.brand-name {
  font-weight: 700;
  font-size: 15.5px;
  letter-spacing: -0.03em;
}

.nav {
  display: flex;
  gap: 2px;
  flex-wrap: wrap;
}

.nav-link {
  padding: 6px 12px;
  border-radius: var(--r-sm);
  color: var(--ink-secondary);
  font-size: 14px;
  font-weight: 500;
  text-decoration: none;
  transition: background var(--transition), color var(--transition);
}

.nav-link:hover {
  background: var(--gray-100);
  color: var(--ink);
}

.nav-link.current {
  background: var(--brand-50);
  color: var(--brand-600);
  font-weight: 600;
}

.account {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-left: auto;
  flex: 0 0 auto;
}

.avatar {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: var(--r-full);
  background: var(--brand-100);
  color: var(--brand-700);
  font-size: 12.5px;
  font-weight: 700;
}

.nickname {
  font-size: 13.5px;
  color: var(--ink-secondary);
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.page {
  max-width: 1080px;
  margin: 0 auto;
  padding: var(--sp-8) var(--sp-5) var(--sp-12);
}

@media (max-width: 760px) {
  .topbar-inner {
    flex-wrap: wrap;
    gap: var(--sp-3);
  }

  .nickname {
    display: none;
  }

  .page {
    padding: var(--sp-5) var(--sp-4) var(--sp-10);
  }
}
</style>
