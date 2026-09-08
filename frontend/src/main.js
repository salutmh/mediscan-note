import { createApp } from 'vue'
import './style.css'
import App from './App.vue'
import { router } from './router'
import { setUnauthorizedHandler } from './api/client'
import { clearSession } from './stores/auth'

// 토큰이 만료/무효/폐기되면 상태를 비우고 화면 0으로.
// **여기서는 logout() 을 쓰지 않는다** — 이미 통하지 않는 토큰으로 서버 로그아웃을
// 다시 호출하면 401 이 또 나서 같은 핸들러가 재진입한다. 로컬만 정리하면 된다.
setUnauthorizedHandler(() => {
  clearSession()
  router.push({ name: 'login' })
})

createApp(App).use(router).mount('#app')
