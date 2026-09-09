/**
 * 로컬 스테이징 검증 — **배포 형태에서만 드러나는 것들.**
 *
 * 기존 E2E 7종은 전부 Vite dev 서버로 돈다. 여기서는 실제 배포와 같은 모양을 만든다:
 * production 빌드를 정적 서버가 서빙하고, API 는 **다른 출처**에 있다.
 *
 * 그래야만 드러나는 것들:
 *
 *   1) 빌드에 박힌 API 주소가 맞는가 (dev 는 그때그때 읽어서 안 걸린다)
 *   2) **CORS 가 실제로 필요해진다** — 출처가 달라야 preflight 가 돈다
 *   3) 자산 서명이 `MEDISCAN_PUBLIC_BASE` 주소로 걸리고 그 주소로 받아지는가
 *   4) **SPA 새로고침** — `/cases/VS-SEG-202` 로 직접 들어와도 앱이 뜨는가
 *      (정적 호스팅에서 fallback 을 빠뜨리면 새로고침마다 404 다)
 *   5) 429·403 같은 오류 응답에도 CORS 헤더가 붙는가 (없으면 "네트워크 오류"로만 보인다)
 *
 * 사용: node verify-staging.mjs <출력폴더> <디버깅포트> [웹주소] [API주소]
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const OUT = process.argv[2] ?? '.'
const PORT = Number(process.argv[3] ?? 9333)
const WEB = process.argv[4] ?? 'http://localhost:4173'
const API = process.argv[5] ?? 'http://127.0.0.1:8010'
mkdirSync(OUT, { recursive: true })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const failures = []
const check = (ok, label, detail = '') => {
  console.log(`  ${ok ? '통과' : '실패'}  ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures.push(label)
}

async function getWsUrl() {
  for (let i = 0; i < 40; i += 1) {
    try {
      const json = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json()
      if (json.webSocketDebuggerUrl) return json.webSocketDebuggerUrl
    } catch {}
    await sleep(250)
  }
  throw new Error('헤드리스 Chrome 디버깅 포트 없음')
}

class Cdp {
  constructor(ws) {
    this.ws = ws
    this.id = 0
    this.pending = new Map()
    this.sessionId = null
    ws.addEventListener('message', (ev) => {
      const msg = JSON.parse(ev.data)
      if (msg.id && this.pending.has(msg.id)) {
        const { resolve, reject } = this.pending.get(msg.id)
        this.pending.delete(msg.id)
        msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result)
      }
    })
  }
  send(method, params = {}) {
    this.id += 1
    const id = this.id
    const payload = { id, method, params }
    if (this.sessionId) payload.sessionId = this.sessionId
    this.ws.send(JSON.stringify(payload))
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject })
      setTimeout(() => {
        if (this.pending.has(id)) {
          this.pending.delete(id)
          reject(new Error(`CDP timeout: ${method}`))
        }
      }, 30000)
    })
  }
}

const ws = new WebSocket(await getWsUrl())
await new Promise((res, rej) => {
  ws.addEventListener('open', res)
  ws.addEventListener('error', rej)
})
const cdp = new Cdp(ws)
const { targetInfos } = await cdp.send('Target.getTargets')
const page = targetInfos.find((t) => t.type === 'page')
const { sessionId } = await cdp.send('Target.attachToTarget', {
  targetId: page.targetId,
  flatten: true,
})
cdp.sessionId = sessionId
await cdp.send('Page.enable')
await cdp.send('Runtime.enable')
await cdp.send('Emulation.setDeviceMetricsOverride', {
  width: 1280,
  height: 900,
  deviceScaleFactor: 1,
  mobile: false,
})

const errors = []
await cdp.send('Log.enable').catch(() => {})
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.method === 'Log.entryAdded' && m.params?.entry?.level === 'error') {
    errors.push(m.params.entry.text)
  }
})

const evaluate = async (expression) => {
  const { result, exceptionDetails } = await cdp.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  })
  if (exceptionDetails) throw new Error(JSON.stringify(exceptionDetails))
  return result.value
}
const goto = async (path, settle = 2500) => {
  await cdp.send('Page.navigate', { url: WEB + path })
  await sleep(settle)
}
const shoot = async (name) => {
  const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, 'base64'))
}

console.log(`웹 ${WEB}  /  API ${API}`)
console.log('')

// ------------------------------------------------- 1) 빌드에 박힌 API 주소
console.log('1) 빌드 산출물')
await goto('/', 3000)
const built = await evaluate(`
  (async () => {
    const html = await (await fetch('/')).text()
    const scripts = [...html.matchAll(/src="(\\/assets\\/[^"]+\\.js)"/g)].map((m) => m[1])
    let bundle = ''
    for (const s of scripts) bundle += await (await fetch(s)).text()
    // 진입 번들이 동적 import 로 갈라져 있으면 index 만으로는 부족하다
    const assets = [...bundle.matchAll(/["'](\\.\\/[^"']+\\.js)["']/g)].map((m) => m[1])
    for (const a of assets.slice(0, 20)) {
      try { bundle += await (await fetch('/assets/' + a.replace('./', ''))).text() } catch {}
    }
    return {
      hasLocalhost8010: /localhost:8010/.test(bundle),
      hasApiBase: bundle.includes(${JSON.stringify(API + '/api')}),
      size: bundle.length,
    }
  })()
`)
check(built.hasApiBase, '빌드에 배포용 API 주소가 박혔다', `${API}/api`)
check(!built.hasLocalhost8010, 'localhost 기본값이 남아 있지 않다')

// ------------------------------------------------------- 2) CORS (교차 출처)
console.log('2) CORS — 출처가 다르다')
// 손으로 OPTIONS 를 만들면 브라우저가 Origin 을 붙이지 않아 서버가 preflight 로
// 보지 않는다(405 가 난다). **실제 교차 출처 요청**을 보내야 브라우저가 스스로
// preflight 를 돌린다 — 그게 배포에서 실제로 일어나는 일이다.
const cors = await evaluate(`
  (async () => {
    try {
      // Content-Type: application/json 은 단순 요청이 아니라 preflight 를 유발한다
      const res = await fetch('${API}/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: 'cors-probe@example.com', password: 'wrong-password-1' }),
      })
      let body = null
      try { body = await res.json() } catch {}
      return { blocked: false, status: res.status, code: (body && body.detail && body.detail.code) || null }
    } catch (e) {
      // CORS 로 막히면 fetch 자체가 TypeError 로 실패한다
      return { blocked: true, message: String(e).slice(0, 120) }
    }
  })()
`)
check(
  !cors.blocked,
  '**교차 출처 요청이 CORS 로 막히지 않는다**',
  cors.blocked ? cors.message : `HTTP ${cors.status}`,
)
check(
  cors.code === 'INVALID_CREDENTIALS',
  '응답 본문까지 읽힌다 (preflight 가 실제로 통과했다)',
  String(cors.code),
)

// 서버가 정말 출처를 보고 있는지 — 모르는 출처에는 허용 헤더를 주면 안 된다
const wrongOrigin = await evaluate(`
  (async () => {
    const res = await fetch('${API}/api/auth/login', {
      method: 'OPTIONS',
      headers: {
        Origin: 'https://evil.example.com',
        'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'content-type',
      },
    })
    return { status: res.status, allowOrigin: res.headers.get('access-control-allow-origin') }
  })()
`)
check(
  wrongOrigin.allowOrigin !== '*' && wrongOrigin.allowOrigin !== 'https://evil.example.com',
  '**모르는 출처는 허용하지 않는다** (와일드카드가 아니다)',
  String(wrongOrigin.allowOrigin),
)


// -------------------------------------------------------- 3) 실제 로그인·자산
console.log('3) 학습 흐름 (교차 출처로)')
const email = `staging${Date.now()}@example.com`
const signedUp = await evaluate(`
  (async () => {
    const res = await fetch('${API}/api/auth/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: ${JSON.stringify(email)}, password: 'pw12345678', nickname: '스테이징',
        consents: { agree_terms: true, agree_privacy: true, agree_sensitive_data: true,
                    agree_ai_notice: true, agree_age14: true, agree_marketing: false },
      }),
    })
    const d = await res.json()
    if (!d.access_token) return 'FAIL ' + JSON.stringify(d).slice(0, 200)
    localStorage.setItem('mediscan.access_token', d.access_token)
    localStorage.setItem('mediscan.user', JSON.stringify({
      user_id: d.user_id, email: d.email, nickname: d.nickname }))
    return 'ok'
  })()
`)
check(signedUp === 'ok', '교차 출처로 가입이 된다', String(signedUp).slice(0, 80))

const caseList = await evaluate(`
  (async () => {
    const res = await fetch('${API}/api/cases', {
      headers: { Authorization: 'Bearer ' + localStorage.getItem('mediscan.access_token') },
    })
    const d = await res.json()
    return { count: (d.cases || []).length, first: (d.cases || [])[0] || null }
  })()
`)
check(caseList.count > 0, '케이스 목록이 온다', `${caseList.count}건`)

// -------------------------------------- 4) 자산 서명이 PUBLIC_BASE 로 걸리는가
console.log('4) 자산 서명 · PUBLIC_BASE')
if (caseList.first) {
  const detail = await evaluate(`
    (async () => {
      const res = await fetch('${API}/api/cases/' + ${JSON.stringify(caseList.first.case_id)}, {
        headers: { Authorization: 'Bearer ' + localStorage.getItem('mediscan.access_token') },
      })
      const d = await res.json()
      const url = d.image_url
      // 브라우저가 그 URL 을 실제로 받을 수 있는지 (img 처럼 헤더 없이)
      const img = await fetch(url)
      return { url, status: img.status, type: img.headers.get('content-type') }
    })()
  `)
  check(
    detail.url.startsWith(API),
    '자산 URL 이 MEDISCAN_PUBLIC_BASE 로 만들어진다',
    detail.url.split('?')[0],
  )
  check(/[?&]s=/.test(detail.url), '서명이 붙어 있다')
  check(
    detail.status === 200 && String(detail.type).startsWith('image/'),
    '**헤더 없이도 그 URL 로 영상이 받아진다** (img 태그가 쓰는 방식)',
    `HTTP ${detail.status} ${detail.type}`,
  )
} else {
  console.log('  건너뜀  케이스가 없다')
}

// ------------------------------------------------- 5) SPA 새로고침 (핵심)
console.log('5) SPA 새로고침 — 배포 후에야 드러나는 것')
const deepLink = await evaluate(`
  (async () => {
    const res = await fetch('/cases/VS-SEG-202', { headers: { Accept: 'text/html' } })
    const text = await res.text()
    return { status: res.status, isHtml: text.includes('<div id="app"'), length: text.length }
  })()
`)
check(
  deepLink.status === 200 && deepLink.isHtml,
  '**깊은 경로로 직접 들어와도 앱이 뜬다** (정적 호스팅에 fallback 이 필요하다)',
  `HTTP ${deepLink.status}`,
)

await goto('/cases/VS-SEG-202', 3500)
const rendered = await evaluate(`
  (() => ({
    path: location.pathname,
    hasApp: Boolean(document.querySelector('#app')?.children.length),
    text: document.body.innerText.replace(/\\s+/g, ' ').slice(0, 120),
  }))()
`)
check(rendered.hasApp, '새로고침 후 화면이 그려진다', rendered.text.slice(0, 60))
await shoot('s01-deep-link')

// ------------------------------------------ 6) 오류 응답에도 CORS 헤더가 붙는가
console.log('6) 오류 응답의 CORS')
const errorCors = await evaluate(`
  (async () => {
    const res = await fetch('${API}/api/cases/NOPE-999', {
      headers: { Authorization: 'Bearer ' + localStorage.getItem('mediscan.access_token') },
    })
    let body = null
    try { body = await res.json() } catch {}
    return { status: res.status, code: body?.detail?.code ?? null }
  })()
`)
check(
  errorCors.status === 404 && errorCors.code === 'CASE_NOT_FOUND',
  '**오류 본문을 교차 출처에서 읽을 수 있다** (CORS 헤더가 없으면 "네트워크 오류"로만 보인다)',
  `${errorCors.status} ${errorCors.code}`,
)

// ------------------------------------------------------------ 결과
console.log('')
const realErrors = errors.filter((e) => !/\b401\b|\b403\b|\b404\b/i.test(e))
if (realErrors.length) {
  console.log('콘솔 에러:')
  realErrors.forEach((e) => console.log('  ' + e))
} else {
  console.log('콘솔 에러 없음 (의도한 401/403/404 제외)')
}
writeFileSync(join(OUT, 'result.json'), JSON.stringify({ failures, errors: realErrors }, null, 2))
console.log(failures.length ? `실패 ${failures.length}건: ${failures.join(', ')}` : '전체 통과')
process.exit(failures.length ? 1 : 0)
