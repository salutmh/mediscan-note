/**
 * 좁은 화면 점검 (v0.7).
 *
 * 학습자가 노트북만 쓸 거라고 가정할 이유가 없다. 여기서 보는 것은
 * **기계로 확실히 알 수 있는 깨짐**뿐이다:
 *
 *   - 가로 스크롤이 생기는가 (내용이 화면 밖으로 밀려났다는 뜻)
 *   - 화면 밖으로 삐져나온 요소가 어느 것인가
 *   - 누르기 힘든 크기의 버튼이 있는가 (권장 최소 44px, 여기서는 32px 미만만 지적)
 *   - 판독 캔버스가 쓸 만한 크기로 남는가
 *
 * "보기 좋은가" 는 판단하지 않는다 — 사람이 스크린샷을 봐야 한다.
 * 지적이 있어도 종료코드는 0 이다 (검토할 목록을 만드는 도구다).
 *
 * 사용: node responsive-check.mjs <출력폴더> <디버깅포트>
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const OUT = process.argv[2] ?? '.'
const PORT = Number(process.argv[3] ?? 9333)
const BASE = 'http://localhost:5173'
const API = 'http://localhost:8010'
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

const evaluate = async (expression) => {
  const { result, exceptionDetails } = await cdp.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  })
  if (exceptionDetails) throw new Error(JSON.stringify(exceptionDetails))
  return result.value
}
const setViewport = (width, height) =>
  cdp.send('Emulation.setDeviceMetricsOverride', {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: width < 600,
  })
const goto = async (path, settle = 2000) => {
  await cdp.send('Page.navigate', { url: BASE + path })
  await sleep(settle)
}
const shoot = async (name) => {
  const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' })
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, 'base64'))
}

// ------------------------------------------------------------------ 로그인
await setViewport(1280, 900)
const email = `resp${Date.now()}@example.com`
await goto('/login')
const ok = await evaluate(`
  (async () => {
    const res = await fetch('${API}/api/auth/signup', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: ${JSON.stringify(email)}, password: 'pw12345678', nickname: '좁은화면',
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
if (ok !== 'ok') {
  console.log(`가입 실패 — ${ok}`)
  process.exit(1)
}

// ------------------------------------------------------------------ 점검
const CHECK = String.raw`
(() => {
  const doc = document.documentElement
  const width = doc.clientWidth

  const visible = (el) => {
    const s = getComputedStyle(el)
    if (s.display === 'none' || s.visibility === 'hidden') return false
    return el.getClientRects().length > 0
  }
  const where = (el) => {
    const cls = (el.className || '').toString().trim().split(/\s+/).filter(Boolean).slice(0, 2).join('.')
    return el.tagName.toLowerCase() + (cls ? '.' + cls : '')
  }

  // 화면 밖으로 삐져나온 요소. 조상이 이미 넘쳤으면 자식은 세지 않는다(같은 원인이 수십 개로 불어난다).
  const overflowing = []
  for (const el of document.body.querySelectorAll('*')) {
    if (!visible(el)) continue
    const r = el.getBoundingClientRect()
    if (r.width === 0) continue
    const over = Math.round(r.right - width)
    if (over > 1) {
      if (overflowing.some((o) => o.node.contains(el))) continue
      overflowing.push({ node: el, el: where(el), over })
    }
  }

  // 누르기 힘든 크기. 44px 이 권장이지만 여기서는 확실히 작은 것만 본다.
  const tiny = []
  for (const el of document.querySelectorAll('button, a[href], input[type=checkbox], input[type=radio]')) {
    if (!visible(el)) continue
    const r = el.getBoundingClientRect()
    if (r.width < 32 || r.height < 32) {
      tiny.push({ el: where(el), size: Math.round(r.width) + 'x' + Math.round(r.height),
                  text: (el.textContent || '').trim().slice(0, 12) })
    }
  }

  const canvas = document.querySelector('canvas.overlay')
  const canvasRect = canvas ? canvas.getBoundingClientRect() : null

  return {
    width,
    horizontalScroll: doc.scrollWidth > width + 1,
    scrollWidth: doc.scrollWidth,
    overflowing: overflowing.map(({ el, over }) => ({ el, over })),
    tiny,
    canvas: canvasRect ? { w: Math.round(canvasRect.width), h: Math.round(canvasRect.height) } : null,
  }
})()
`

const VIEWPORTS = [
  [390, 844, '휴대폰 (390)'],
  [768, 1024, '태블릿 세로 (768)'],
  [1024, 768, '태블릿 가로 (1024)'],
]
const PAGES = [
  ['/cases', '케이스 목록'],
  ['/cases/VS-SEG-202', '판독훈련'],
  ['/wrong-notes', '복습노트'],
  ['/progress', '진행현황'],
  ['/account', '계정 설정'],
]

const all = []
let issues = 0
for (const [w, h, vpLabel] of VIEWPORTS) {
  console.log('')
  console.log(`── ${vpLabel} ${'─'.repeat(40)}`)
  await setViewport(w, h)
  for (const [path, label] of PAGES) {
    await goto(path, 2000)
    const r = await evaluate(CHECK)
    all.push({ viewport: vpLabel, path, label, ...r })

    const problems = []
    if (r.horizontalScroll) problems.push(`가로스크롤(${r.scrollWidth}px > ${r.width}px)`)
    if (r.overflowing.length) problems.push(`화면밖 ${r.overflowing.length}개`)
    if (r.tiny.length) problems.push(`작은버튼 ${r.tiny.length}개`)
    issues += problems.length

    const canvasNote = r.canvas ? ` 캔버스 ${r.canvas.w}x${r.canvas.h}` : ''
    console.log(
      `${problems.length ? '지적' : '통과'}  ${label.padEnd(12)}${canvasNote.padEnd(22)}` +
        (problems.join(' / ') || '문제 없음'),
    )
    for (const o of r.overflowing.slice(0, 5)) console.log(`        화면밖 ${o.over}px: ${o.el}`)
    for (const t of r.tiny.slice(0, 5)) console.log(`        작은버튼 ${t.size}: ${t.el} "${t.text}"`)

    if (problems.length) await shoot(`${w}-${label.replace(/\s/g, '')}`)
  }
}

writeFileSync(join(OUT, 'responsive-report.json'), JSON.stringify(all, null, 2))
console.log('')
console.log(issues ? `총 ${issues}건 지적 (스크린샷: ${OUT})` : '지적 사항 없음')
process.exit(0)
