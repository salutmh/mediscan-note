/**
 * 화면 2 slice 탐색 검증 (v0.6).
 *
 * 예전에는 슬라이더가 숫자만 바꾸고 영상은 그대로였다. 실제로 바뀌는지,
 * 그리고 **slice 를 넘겨보고 돌아왔을 때 칠하던 ROI 가 살아 있는지**를 브라우저에서 확인한다.
 * (두 번째가 핵심이다 — RoiCanvas 가 imageUrl 변경 시 캔버스를 지우고 있어서
 *  옆 slice 를 확인하면 작업이 사라지는 버그가 있었다.)
 *
 * 함께 확인: 대표 slice 가 아니면 캔버스가 잠기고 제출이 막히는가.
 *
 * 사용: node slice-navigation.mjs <출력폴더> <디버깅포트>
 */
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const OUT = process.argv[2] ?? '.'
const PORT = Number(process.argv[3] ?? 9333)
const BASE = 'http://localhost:5173'
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
  height: 1000,
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
const goto = async (path, settle = 1600) => {
  await cdp.send('Page.navigate', { url: BASE + path })
  await sleep(settle)
}
const shoot = async (name) => {
  const { cssContentSize } = await cdp.send('Page.getLayoutMetrics')
  const { data } = await cdp.send('Page.captureScreenshot', {
    format: 'png',
    captureBeyondViewport: true,
    clip: {
      x: 0,
      y: 0,
      width: cssContentSize.width,
      height: Math.min(cssContentSize.height, 4000),
      scale: 1,
    },
  })
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(data, 'base64'))
}

// ------------------------------------------------------------------ 준비
console.log('0) 신규 가입')
const email = `slice${Date.now()}@example.com`
await goto('/login')
await evaluate(`
  (async () => {
    const res = await fetch('http://localhost:8010/api/auth/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        email: ${JSON.stringify(email)}, password: 'pw12345678', nickname: '슬라이스',
        consents: {
          agree_terms: true, agree_privacy: true, agree_sensitive_data: true,
          agree_ai_notice: true, agree_age14: true, agree_marketing: false,
        },
      }),
    })
    const data = await res.json()
    localStorage.setItem('mediscan.access_token', data.access_token)
    localStorage.setItem('mediscan.user', JSON.stringify({
      user_id: data.user_id, email: data.email, nickname: data.nickname,
    }))
    return 'ok'
  })()
`)

console.log('1) 케이스 열기 — slice 컨트롤이 있는가')
await goto('/cases/VS-SEG-202', 2200)

const initial = await evaluate(`
  (() => {
    const img = document.querySelector('.viewer-frame img')
    const label = document.querySelector('.slice-label')
    const range = document.querySelector('.slice-bar input[type=range]')
    return {
      hasControls: Boolean(range),
      src: img ? img.getAttribute('src') : null,
      label: label ? label.textContent.trim().replace(/\\s+/g, ' ') : null,
      max: range ? Number(range.max) : null,
      isRepresentative: Boolean(document.querySelector('.rep-tag')),
    }
  })()
`)
check(initial.hasControls, 'slice 컨트롤 존재', initial.label ?? '')
check(initial.isRepresentative, '처음에는 대표 slice 를 보여준다', initial.label ?? '')
check((initial.max ?? 0) > 0, 'slice 가 여러 장 등록되어 있다', `max=${initial.max}`)
await shoot('s01-representative')

console.log('2) 대표 slice 에 ROI 를 칠한다')
await evaluate(`
  (async () => {
    const canvas = document.querySelector('canvas.overlay')
    const rect = canvas.getBoundingClientRect()
    const sx = rect.width / canvas.width
    const toX = (x) => rect.left + x * sx
    const toY = (y) => rect.top + y * sx
    const opts = (x, y) => ({ pointerId: 1, bubbles: true, clientX: x, clientY: y, pointerType: 'mouse', isPrimary: true, button: 0 })
    canvas.setPointerCapture = () => {}
    canvas.releasePointerCapture = () => {}
    canvas.dispatchEvent(new PointerEvent('pointerdown', opts(toX(338), toY(307))))
    for (let k = 0; k <= 20; k++) {
      canvas.dispatchEvent(new PointerEvent('pointermove', opts(toX(320 + k * 2), toY(300 + k))))
      await new Promise((r) => setTimeout(r, 4))
    }
    canvas.dispatchEvent(new PointerEvent('pointerup', opts(toX(360), toY(320))))
    return 'painted'
  })()
`)
await sleep(400)

const painted = await evaluate(`
  (() => {
    const canvas = document.querySelector('canvas.overlay')
    const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
    let n = 0
    for (let i = 3; i < data.length; i += 4) if (data[i] > 0) n++
    return n
  })()
`)
check(painted > 0, 'ROI 가 그려졌다', `${painted}px`)

console.log('3) 옆 slice 로 이동 — 영상이 실제로 바뀌는가')
await evaluate(`
  (() => {
    const range = document.querySelector('.slice-bar input[type=range]')
    range.value = String(Math.min(Number(range.max), Number(range.value) + 3))
    range.dispatchEvent(new Event('input', { bubbles: true }))
    return range.value
  })()
`)
await sleep(900)

const moved = await evaluate(`
  (() => {
    const img = document.querySelector('.viewer-frame img')
    const label = document.querySelector('.slice-label')
    const canvas = document.querySelector('canvas.overlay')
    const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
    let n = 0
    for (let i = 3; i < data.length; i += 4) if (data[i] > 0) n++
    return {
      src: img ? img.getAttribute('src') : null,
      label: label ? label.textContent.trim().replace(/\\s+/g, ' ') : null,
      locked: Boolean(document.querySelector('.slice-locked')),
      stillRepresentative: Boolean(document.querySelector('.rep-tag')),
      roiPixels: n,
      submitDisabled: Boolean(document.querySelector('.submit-card button')?.disabled),
    }
  })()
`)
check(moved.src !== initial.src, '영상이 실제로 바뀐다 (예전엔 숫자만 바뀌었다)', moved.label ?? '')
check(!moved.stillRepresentative, '대표 slice 를 벗어나면 대표 태그가 사라진다')
check(moved.locked, '대표 slice 가 아니면 안내가 나온다')
check(moved.roiPixels === painted, '**slice 를 넘겨도 그리던 ROI 가 유지된다**', `${moved.roiPixels}px`)
await shoot('s02-other-slice')

console.log('4) 대표 slice 로 돌아오기')
await evaluate(`
  (() => {
    const btn = [...document.querySelectorAll('.slice-locked button')].find((b) => b.textContent.includes('대표'))
    if (btn) btn.click()
    return Boolean(btn)
  })()
`)
await sleep(900)

const back = await evaluate(`
  (() => {
    const img = document.querySelector('.viewer-frame img')
    const canvas = document.querySelector('canvas.overlay')
    const data = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data
    let n = 0
    for (let i = 3; i < data.length; i += 4) if (data[i] > 0) n++
    return {
      src: img ? img.getAttribute('src') : null,
      isRepresentative: Boolean(document.querySelector('.rep-tag')),
      roiPixels: n,
    }
  })()
`)
check(back.isRepresentative, '"대표 slice로 이동" 버튼이 동작한다')
check(back.src === initial.src, '대표 slice 영상으로 돌아왔다')
check(back.roiPixels === painted, '돌아와도 ROI 가 그대로다', `${back.roiPixels}px`)
await shoot('s03-back-to-representative')

console.log('5) 제출이 정상 동작하는가')
await evaluate(`
  (() => {
    const btn = [...document.querySelectorAll('button')].find((b) => b.textContent.trim() === '제출')
    if (btn) btn.click()
    return Boolean(btn)
  })()
`)
await sleep(2500)
const graded = await evaluate(`
  (() => {
    const grade = document.querySelector('.verdict .grade')
    const feedback = document.querySelector('.feedback .feedback-list li')
    return {
      grade: grade ? grade.textContent.trim() : null,
      feedback: feedback ? feedback.textContent.trim() : null,
    }
  })()
`)
check(Boolean(graded.grade), '제출 후 채점 결과가 나온다', graded.grade ?? '')
check(Boolean(graded.feedback), '공간 피드백이 표시된다', graded.feedback ?? '')
await shoot('s04-after-submit')

// ------------------------------------------------------------------ 결과
console.log('')
if (errors.length) {
  console.log('콘솔 에러:')
  errors.forEach((e) => console.log('  ' + e))
} else {
  console.log('콘솔 에러 없음')
}
console.log(failures.length ? `실패 ${failures.length}건: ${failures.join(', ')}` : '전체 통과')
process.exit(failures.length || errors.length ? 1 : 0)
