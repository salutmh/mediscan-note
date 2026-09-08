import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import { router } from './router'
import { setUnauthorizedHandler } from './api/client'
import { logout } from './stores/auth'

// 토큰이 만료/무효면 상태를 비우고 화면 0으로.
setUnauthorizedHandler(() => {
  logout()
  router.push({ name: 'login' })
})

createApp(App).use(router).mount('#app')
