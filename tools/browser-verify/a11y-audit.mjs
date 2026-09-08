/**
 * 접근성 기본 점검 (v0.7).
 *
 * 자동 점검이 사람 검수를 대신하지는 못한다. 여기서 보는 것은
 * **기계로 확실히 알 수 있는 것**뿐이다:
 *
 *   - 이미지에 대체 텍스트가 있는가 (장식용이면 alt="" 로 명시)
 *   - 버튼·링크에 읽을 이름이 있는가 (아이콘만 있는 버튼이 흔한 원인)
 *   - 입력에 연결된 label 이 있는가 (placeholder 는 label 이 아니다)
 *   - canvas 처럼 대체 수단이 필요한 요소에 설명이 있는가
 *   - 제목(h1~h6) 단계를 건너뛰지 않는가
 *   - <html lang> 과 문서 제목이 있는가
 *
 * "색 대비가 충분한가", "키보드만으로 ROI 를 그릴 수 있는가" 같은 것은 여기서
 * 판단하지 않는다 — 사람이 봐야 한다.
 *
 * 사용: node a11y-audit.mjs <출력폴더> <디버깅포트>
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const OUT = process.argv[2] ?? '.'
const PORT = Number(process.argv[3] ?? 9333)
const BASE = 'http://localhost:5173'
mkdirSync(OUT, { recursive: true })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

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
  height: 1000,
  deviceScaleFactor: 1,
  mobile: false,
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
const goto = async (path, settle = 1600) => {
  await cdp.send('Page.navigate', { url: BASE + path })
  await sleep(settle)
}

// ------------------------------------------------------------------ 로그인
// 화면 1~7 은 로그인 상태여야 실제 내용을 그린다. 반대로 **로그인 화면은 로그아웃
// 상태에서 봐야 한다** — 로그인한 채로 /login 을 열면 /cases 로 넘어가버려서
// 정작 입력이 가장 많은 화면이 점검에서 빠진다. (실제로 그렇게 빠뜨렸다.)
const email = `a11y${Date.now()}@example.com`
await goto('/login')
const signedIn = await evaluate(`
  (async () => {
    const res = await fetch('http://localhost:8010/api/auth/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: ${JSON.stringify(email)}, password: 'pw12345678', nickname: '접근성',
        consents: {
          agree_terms: true, agree_privacy: true, agree_sensitive_data: true,
          agree_ai_notice: true, agree_age14: true, agree_marketing: false,
        },
      }),
    })
    const data = await res.json()
    if (!data.access_token) return 'FAIL ' + JSON.stringify(data).slice(0, 200)
    return JSON.stringify({
      token: data.access_token,
      user: JSON.stringify({ user_id: data.user_id, email: data.email, nickname: data.nickname }),
    })
  })()
`)
if (signedIn.startsWith('FAIL')) {
  console.log(`가입 실패 — ${signedIn}`)
  console.log('(비밀번호 정책 8자 / rate limit 을 확인하세요)')
  process.exit(1)
}
const { token: TOKEN, user: USER } = JSON.parse(signedIn)

// ------------------------------------------------------------------ 점검
const AUDIT = String.raw`
(() => {
  const visible = (el) => {
    const s = getComputedStyle(el)
    if (s.display === 'none' || s.visibility === 'hidden') return false
    return el.getClientRects().length > 0
  }
  // 스크린리더가 이 요소를 무엇이라고 읽을지. 완전한 구현은 아니고 흔한 경우만 본다.
  const nameOf = (el) => {
    const aria = el.getAttribute('aria-label')
    if (aria && aria.trim()) return aria.trim()
    const labelledby = el.getAttribute('aria-labelledby')
    if (labelledby) {
      const t = labelledby
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.textContent ?? '')
        .join(' ')
      if (t.trim()) return t.trim()
    }
    if (el.title && el.title.trim()) return el.title.trim()
    const text = (el.textContent || '').trim()
    if (text) return text
    const img = el.querySelector('img[alt]')
    if (img && img.alt.trim()) return img.alt.trim()
    if (el.tagName === 'INPUT') return (el.value || '').trim()
    return ''
  }
  const where = (el) => {
    const cls = (el.className || '').toString().trim().split(/\s+/).filter(Boolean).slice(0, 2).join('.')
    return el.tagName.toLowerCase() + (cls ? '.' + cls : '') + (el.id ? '#' + el.id : '')
  }

  const issues = []
  const add = (rule, el, detail) => issues.push({ rule, el: where(el), detail: detail || '' })

  // 1) 이미지 대체 텍스트. 장식용이면 alt="" 로 **명시**해야 한다 (속성 자체가 없는 것과 다르다).
  for (const img of document.querySelectorAll('img')) {
    if (!visible(img)) continue
    if (img.getAttribute('alt') === null) {
      add('img-alt-missing', img, (img.getAttribute('src') || '').slice(-40))
    }
  }
  // 2) 버튼·링크에 읽을 이름이 있는가. 아이콘만 있는 버튼이 흔한 원인이다.
  for (const el of document.querySelectorAll('button, a[href], [role=button]')) {
    if (!visible(el)) continue
    if (!nameOf(el)) add('no-accessible-name', el)
  }
  // 3) 입력에 연결된 label. placeholder 는 label 이 아니다 (입력하면 사라진다).
  for (const el of document.querySelectorAll('input, select, textarea')) {
    if (!visible(el) || el.type === 'hidden') continue
    const byFor = el.id ? document.querySelector('label[for="' + CSS.escape(el.id) + '"]') : null
    const wrapping = el.closest('label')
    const aria = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')
    if (!byFor && !wrapping && !aria) {
      add('input-without-label', el, el.type + (el.placeholder ? ' placeholder="' + el.placeholder + '"' : ''))
    }
  }
  // 4) canvas 는 내용이 픽셀뿐이라 대체 설명이 없으면 아무것도 전달되지 않는다.
  for (const el of document.querySelectorAll('canvas')) {
    if (!visible(el)) continue
    if (!el.getAttribute('aria-label') && !el.getAttribute('role') && !el.textContent.trim()) {
      add('canvas-without-description', el)
    }
  }
  // 5) 제목 단계 건너뜀 — 스크린리더 사용자는 제목으로 화면 구조를 훑는다.
  const levels = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')]
    .filter(visible)
    .map((h) => ({ n: Number(h.tagName[1]), text: (h.textContent || '').trim().slice(0, 30), el: h }))
  for (let i = 1; i < levels.length; i += 1) {
    if (levels[i].n - levels[i - 1].n > 1) {
      add('heading-level-skipped', levels[i].el,
        'h' + levels[i - 1].n + ' -> h' + levels[i].n + ' "' + levels[i].text + '"')
    }
  }
  if (levels.length && levels[0].n !== 1) {
    add('no-h1', document.body, '첫 제목이 h' + levels[0].n)
  }

  return {
    lang: document.documentElement.getAttribute('lang'),
    title: document.title,
    headings: levels.map((l) => 'h' + l.n + ' ' + l.text),
    // 무엇을 보고 판단했는지. "0건 지적"이 제대로 본 결과인지, 화면이 안 그려진
    // 탓인지 구분하기 위해 남긴다.
    saw: {
      inputs: [...document.querySelectorAll('input, select, textarea')].filter(visible).length,
      buttons: [...document.querySelectorAll('button, a[href]')].filter(visible).length,
      images: [...document.querySelectorAll('img')].filter(visible).length,
      canvases: [...document.querySelectorAll('canvas')].filter(visible).length,
    },
    issues,
  }
})()
`

// 로그인 화면은 위에서 로그아웃 상태로 이미 점검했다 (여기 넣으면 /cases 로 넘어간다)
const PAGES = [
  ['/cases', '화면 1 케이스 목록'],
  ['/cases/VS-SEG-202', '화면 2 판독훈련'],
  ['/analyze', '화면 5 내 영상 분석'],
  ['/wrong-notes', '화면 6 복습노트'],
  ['/progress', '화면 7 진행현황'],
  ['/account', '계정 설정'],
]

const all = []
const report = (path, label, r) => {
  all.push({ path, label, ...r })
  const counts = {}
  for (const i of r.issues) counts[i.rule] = (counts[i.rule] ?? 0) + 1
  const summary = Object.entries(counts).map(([k, v]) => `${k}=${v}`).join(' ')
  const saw = `[입력${r.saw.inputs} 버튼${r.saw.buttons} 이미지${r.saw.images} 캔버스${r.saw.canvases}]`
  console.log(`${r.issues.length === 0 ? '통과' : '지적'}  ${label.padEnd(22)} ${saw.padEnd(34)} ${summary || '문제 없음'}`)
  for (const i of r.issues) {
    console.log(`        ${i.rule}: ${i.el}${i.detail ? ' — ' + i.detail : ''}`)
  }
}

// 1) 로그아웃 상태의 로그인 화면.
// 탭은 쿼리 파라미터가 아니라 **버튼**이다 (?tab=signup 으로는 안 바뀐다 —
// 처음에 그렇게 넣었다가 로그인 탭을 두 번 본 꼴이 됐다). 실제로 눌러서 전환한다.
const clickTab = async (text) =>
  evaluate(`(() => {
    const b = [...document.querySelectorAll('.tabs button, button')]
      .find((x) => x.textContent.trim() === ${JSON.stringify(text)})
    if (!b) return 'not-found'
    b.click()
    return 'clicked'
  })()`)

await evaluate(`(() => { localStorage.clear(); return 'cleared' })()`)
await goto('/login', 2200)
report('/login', '화면 0 로그인', await evaluate(AUDIT))

for (const [tab, label] of [['회원가입', '화면 0 회원가입'], ['비밀번호 재설정', '화면 0 비밀번호 재설정']]) {
  const clicked = await clickTab(tab)
  if (clicked !== 'clicked') {
    console.log(`건너뜀  ${label} — 탭 버튼을 찾지 못했다`)
    continue
  }
  await sleep(600)
  report('/login (' + tab + ')', label, await evaluate(AUDIT))
}

// 2) 로그인 상태의 나머지 화면
await evaluate(`(() => {
  localStorage.setItem('mediscan.access_token', ${JSON.stringify('__TOKEN__')})
  localStorage.setItem('mediscan.user', ${JSON.stringify('__USER__')})
  return 'restored'
})()`.replace('"__TOKEN__"', JSON.stringify(TOKEN)).replace('"__USER__"', JSON.stringify(USER)))

for (const [path, label] of PAGES) {
  await goto(path, 2200)
  report(path, label, await evaluate(AUDIT))
}

console.log('')
console.log(`<html lang>     ${all[0].lang ?? '없음 (스크린리더 발음이 갈린다)'}`)
console.log(`document.title  ${all[0].title || '없음'}`)

writeFileSync(join(OUT, 'a11y-report.json'), JSON.stringify(all, null, 2))
const total = all.reduce((n, p) => n + p.issues.length, 0)
console.log('')
console.log(total ? `총 ${total}건 지적 (상세: ${join(OUT, 'a11y-report.json')})` : '지적 사항 없음')
// 점검 도구다. 지적이 있다고 비정상 종료하지 않는다 — 사람이 보고 판단할 목록이다.
process.exit(0)
