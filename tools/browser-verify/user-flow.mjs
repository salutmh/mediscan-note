/**
 * DB 연동 후 실제 사용자 흐름을 헤드리스 Chrome 으로 끝까지 밟아본다.
 *   신규 가입 -> 케이스 목록(전부 미해결) -> 일부러 틀리게 제출 -> 복습노트에 쌓임
 *   -> 재도전해서 맞히기 -> 복습노트에서 빠짐 -> 진행현황 반영
 * 사용: node flow.mjs <출력폴더> <디버깅포트>
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const OUT = process.argv[2] ?? '.'
const PORT = Number(process.argv[3] ?? 9334)
const BASE = 'http://localhost:5173'
mkdirSync(OUT, { recursive: true })

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function getWsUrl() {
  for (let i = 0; i < 40; i += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/version`)
      const json = await res.json()
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
const { sessionId } = await cdp.send('Target.attachToTarget', { targetId: page.targetId, flatten: true })
cdp.sessionId = sessionId
await cdp.send('Page.enable')
await cdp.send('Runtime.enable')
await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false })

const errors = []
await cdp.send('Log.enable').catch(() => {})
ws.addEventListener('message', (ev) => {
  const m = JSON.parse(ev.data)
  if (m.method === 'Log.entryAdded' && m.params?.entry?.level === 'error') errors.push(m.params.entry.text)
})

const goto = async (path, settle = 1500) => {
  await cdp.send('Page.navigate', { url: BASE + path })
  await sleep(settle)
}
const evaluate = async (expression) => {
  const { result, exceptionDetails } = await cdp.send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
  })
  if (exceptionDetails) throw new Error(JSON.stringify(exceptionDetails))
  return result.value
}
const shoot = async (name) => {
  const { cssContentSize } = await cdp.send('Page.getLayoutMetrics')
  const { data } = await cdp.send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: true,
    // 해설 3층 구조가 붙으면서 페이지가 길어졌다. 잘리면 검증 스크린샷의 의미가 없다.
    clip: { x: 0, y: 0, width: cssContentSize.width, height: Math.min(cssContentSize.height, 5000), scale: 1 },
  })
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, 'base64'))
  console.log(`  저장: ${name}.png`)
}

/**
 * 캔버스 위를 브러시로 **칠한다** (동심원 여러 겹 + 중심 통과).
 * v0.3에서 서버가 ROI 내부 구멍을 자동으로 메우지 않으므로, 실제 사용자처럼 면적을 채워야 한다.
 * 화면 안내도 "이상으로 판단되는 부위를 칠해주세요"로 통일되어 있다.
 */
const paint = (cx, cy, r) => evaluate(`
  (async () => {
    const canvas = document.querySelector('canvas.overlay')
    if (!canvas) return 'no canvas'
    const rect = canvas.getBoundingClientRect()
    const sx = rect.width / canvas.width
    const toX = (x) => rect.left + x * sx
    const toY = (y) => rect.top + y * sx
    const opts = (x, y) => ({ pointerId: 1, bubbles: true, clientX: x, clientY: y, pointerType: 'mouse', isPrimary: true, button: 0 })
    canvas.setPointerCapture = () => {}
    canvas.releasePointerCapture = () => {}

    const rings = [${'`'}${'`'}]
    canvas.dispatchEvent(new PointerEvent('pointerdown', opts(toX(${cx}), toY(${cy}))))
    for (const frac of [0.25, 0.55, 0.85]) {
      const rr = ${r} * frac
      for (let k = 0; k <= 24; k++) {
        const a = 2 * Math.PI * k / 24
        canvas.dispatchEvent(new PointerEvent('pointermove', opts(toX(${cx} + rr * Math.cos(a)), toY(${cy} + rr * Math.sin(a)))))
        await new Promise((r2) => setTimeout(r2, 3))
      }
    }
    canvas.dispatchEvent(new PointerEvent('pointerup', opts(toX(${cx}), toY(${cy}))))
    return 'painted'
  })()
`)

/**
 * 기준 마스크 모양을 그대로 따라 칠한다 — 재도전이 안정적으로 `일치` 가 나오게 하기 위한 것이다.
 *
 * 왜 원(circle)이 아니라 마스크를 따라 칠하나:
 *   실제 병변은 불규칙해서 같은 중심의 원으로는 Dice 가 0.63 언저리에 머문다.
 *   임계값(0.60)에 너무 가까워서, 케이스를 바꾸거나 브러시가 1~2px 어긋나면 E2E 가 흔들린다.
 *   **채점 임계값은 그대로 두고**, "병변을 정확히 칠한 사용자"를 재현하도록 입력 쪽을 고쳤다.
 *
 * 방법: 마스크를 브러시 반지름만큼 침식(erosion)한 뒤 가로 스캔라인으로 칠한다.
 *   침식해두면 둥근 붓끝이 GT 밖으로 삐져나가지 않으므로 과도하게 칠할 일이 없고,
 *   칠한 영역이 GT 안에 들어오므로 Dice 는 (칠한 면적/GT 면적)으로만 결정된다.
 */
const paintMask = (maskUrl, brush = 10) => evaluate(`
  (async () => {
    const canvas = document.querySelector('canvas.overlay')
    if (!canvas) return 'no canvas'

    // 브러시를 가늘게 — 굵으면 침식 후 남는 면적이 줄어든다
    const range = document.querySelector('.size input[type=range]')
    if (range) {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(range, String(${brush}))
      range.dispatchEvent(new Event('input', { bubbles: true }))
      await new Promise((r) => setTimeout(r, 50))
    }

    const img = new Image()
    img.crossOrigin = 'anonymous'
    img.src = ${JSON.stringify(maskUrl)}
    await img.decode()
    const off = document.createElement('canvas')
    off.width = img.naturalWidth
    off.height = img.naturalHeight
    const octx = off.getContext('2d', { willReadFrequently: true })
    octx.drawImage(img, 0, 0)
    const w = off.width
    const h = off.height
    const data = octx.getImageData(0, 0, w, h).data
    // 백엔드 masks.py 와 같은 판정 규칙 (투명 배경 + 불투명 마스크)
    const on = (x, y) => x >= 0 && y >= 0 && x < w && y < h && data[(y * w + x) * 4 + 3] > 16

    let x0 = w, y0 = h, x1 = -1, y1 = -1
    for (let y = 0; y < h; y++) {
      for (let x = 0; x < w; x++) {
        if (data[(y * w + x) * 4 + 3] > 16) {
          if (x < x0) x0 = x
          if (x > x1) x1 = x
          if (y < y0) y0 = y
          if (y > y1) y1 = y
        }
      }
    }
    if (x1 < 0) return 'empty mask'

    const r = Math.ceil(${brush} / 2)
    const offsets = []
    for (let dy = -r; dy <= r; dy++) {
      for (let dx = -r; dx <= r; dx++) if (dx * dx + dy * dy <= r * r) offsets.push([dx, dy])
    }
    const inside = (x, y) => offsets.every(([dx, dy]) => on(x + dx, y + dy))

    const rect = canvas.getBoundingClientRect()
    const s = rect.width / canvas.width
    const toX = (x) => rect.left + (x + 0.5) * s
    const toY = (y) => rect.top + (y + 0.5) * s
    const opts = (x, y) => ({ pointerId: 1, bubbles: true, clientX: x, clientY: y, pointerType: 'mouse', isPrimary: true, button: 0 })
    canvas.setPointerCapture = () => {}
    canvas.releasePointerCapture = () => {}

    let strokes = 0
    let covered = 0
    for (let y = y0; y <= y1; y += r) {   // 행 간격 <= 반지름이라 스트로크끼리 겹친다
      let run = null
      for (let x = x0; x <= x1 + 1; x++) {
        const ok = x <= x1 && inside(x, y)
        if (ok && run === null) run = x
        if (!ok && run !== null) {
          const end = x - 1
          canvas.dispatchEvent(new PointerEvent('pointerdown', opts(toX(run), toY(y))))
          canvas.dispatchEvent(new PointerEvent('pointermove', opts(toX(end), toY(y))))
          canvas.dispatchEvent(new PointerEvent('pointerup', opts(toX(end), toY(y))))
          strokes += 1
          covered += end - run + 1
          run = null
        }
      }
    }
    await new Promise((r2) => setTimeout(r2, 100))
    return 'strokes=' + strokes + ' 중심선 ' + covered + 'px (bbox ' + x0 + ',' + y0 + '~' + x1 + ',' + y1 + ')'
  })()
`)

/** submit/retry 응답을 가로채 둔다 — 기준 마스크 URL 은 제출 응답에만 들어 있다. */
const installResponseSpy = () => evaluate(`
  (() => {
    if (window.__mediscanSpy) return 'already'
    window.__mediscanSpy = true
    const orig = window.fetch
    window.fetch = async (...args) => {
      const res = await orig(...args)
      const url = typeof args[0] === 'string' ? args[0] : args[0]?.url
      if (url && (url.includes('/submit') || url.includes('/retry'))) {
        res.clone().json().then((j) => { window.__lastResult = j }).catch(() => {})
      }
      return res
    }
    return 'installed'
  })()
`)

const lastResult = () => evaluate('window.__lastResult ?? null')

const clickText = (text) => evaluate(`
  (() => {
    const el = [...document.querySelectorAll('button, a')].find((b) => b.textContent.trim() === ${JSON.stringify(text)})
    el?.click()
    return el ? 'clicked' : 'not found: ' + ${JSON.stringify(text)}
  })()
`)

const readGrade = () => evaluate(`
  (() => {
    const g = document.querySelector('.verdict .grade')
    const metrics = [...document.querySelectorAll('.metrics dd')].map((d) => d.textContent.trim())
    return g ? g.textContent.trim() + ' / ' + metrics.join(' , ') : 'no result'
  })()
`)

// ---------------------------------------------------------------------------
const failures = []
const email = `flow${Date.now()}@example.com`
console.log('1) 신규 가입:', email)
await goto('/login', 800)
await evaluate("localStorage.clear(); 'ok'")
await goto('/login', 1800)
await clickText('회원가입')
await sleep(400)
await evaluate(`
  (async () => {
    const set = (el, v) => {
      el.value = v
      el.dispatchEvent(new Event('input', { bubbles: true }))
    }
    const inputs = document.querySelectorAll('.field input')
    set(inputs[0], ${JSON.stringify(email)})
    set(inputs[1], 'pw1234')
    set(inputs[2], '흐름테스트')
    await new Promise((r) => setTimeout(r, 100))
    // 전체 동의 체크
    document.querySelector('.consents .row.all input').click()
    return 'filled'
  })()
`)
await sleep(400)
await shoot('f01-signup-filled')
await clickText('가입 완료')
await sleep(2200)
await shoot('f02-after-signup')
console.log('   현재 경로:', await evaluate('location.pathname'))

console.log('2) 케이스 목록 — 전부 미해결이어야 함')
await goto('/cases', 1800)
console.log('   ', await evaluate(`[...document.querySelectorAll('.case-card .badge')].map(b=>b.textContent.trim()).join(', ')`))
await shoot('f03-cases-fresh')

console.log('3) VS-SEG-202 를 일부러 엉뚱한 곳(반대쪽 뇌실질)에 표시하고 제출')
await goto('/cases/VS-SEG-202', 2000)
await installResponseSpy()
await paint(330, 180, 25)
await sleep(300)
await clickText('제출')
await sleep(2200)
console.log('   결과:', await readGrade())
await shoot('f04-mismatch-result')

// 기준 마스크 URL 은 제출 응답에만 들어 있다 (GET /api/cases/{id} 는 내려주지 않는다).
const referenceMaskUrl = (await lastResult())?.reference_mask_url
if (!referenceMaskUrl) throw new Error('제출 응답에서 reference_mask_url 을 얻지 못했습니다')
console.log('   기준 마스크:', referenceMaskUrl)

console.log('4) 복습노트에 쌓였는지')
await goto('/wrong-notes', 1800)
console.log('   ', await evaluate(`[...document.querySelectorAll('.row .case-id')].map(e=>e.textContent.trim()).join(', ') || '(빈 목록)'`))
await shoot('f05-review-notes')

console.log('5) 재도전 — 기준 마스크 모양을 따라 칠해서 제출')
await clickText('재도전')
await sleep(2200)
console.log('   현재 경로:', await evaluate('location.pathname'))
await installResponseSpy()
console.log('   칠하기:', await paintMask(referenceMaskUrl, 10))
await sleep(300)
await clickText('제출')
await sleep(2200)
console.log('   결과:', await readGrade())
await shoot('f06-retry-match')

// 임계값(0.60)에 아슬아슬하게 걸치면 반복 실행 때 E2E 가 흔들린다. 여유를 확인한다.
const retry = await lastResult()
const MIN_DICE = 0.85
if (retry?.grade !== 'match') failures.push('재도전이 match 가 아님: ' + retry?.grade + ' (dice ' + retry?.dice + ')')
if (!(retry?.dice >= MIN_DICE)) failures.push('재도전 Dice ' + retry?.dice + ' < 기대치 ' + MIN_DICE + ' — 브러시 재현이 불안정합니다')
console.log('   Dice ' + retry?.dice + ' (채점 임계값 0.60, E2E 기대치 ' + MIN_DICE + ' 이상)')

console.log('6) 복습노트에서 빠졌는지')
await goto('/wrong-notes', 1800)
console.log('   ', await evaluate(`[...document.querySelectorAll('.row .case-id')].map(e=>e.textContent.trim()).join(', ') || '(빈 목록)'`))
await shoot('f07-review-after')

console.log('7) 진행현황 반영')
await goto('/progress', 1800)
console.log('   해결률:', await evaluate(`document.querySelector('.gauge-value')?.textContent.trim()`))
console.log('   케이스:', await evaluate(`document.querySelector('.hero-count')?.textContent.trim()`))
await shoot('f08-progress')

console.log(errors.length ? `\n콘솔 에러:\n  ${errors.slice(0, 8).join('\n  ')}` : '\n콘솔 에러 없음')
if (errors.length) failures.push('콘솔 에러 ' + errors.length + '건')

if (failures.length) {
  console.log('')
  console.log('실패:')
  for (const f of failures) console.log('  - ' + f)
  ws.close()
  process.exit(1)
}
console.log('')
console.log('전체 통과')
ws.close()
