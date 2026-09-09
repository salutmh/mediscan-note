/**
 * production 빌드(dist/)를 정적 서버로 띄운다 — **배포와 같은 형태로.**
 *
 * ==========================================================================
 * **왜 필요한가 — 지금까지 Vite dev 서버로만 검증했다.**
 * ==========================================================================
 * E2E 7종이 전부 `npm run dev` 로 돌았다. 실제 배포는 다르다:
 *
 *   - `VITE_API_BASE` 가 **빌드 시점에** 번들로 들어간다 (dev 는 그때그때 읽는다)
 *   - API 가 **다른 출처**에 있다 (dev 는 프록시 없이도 localhost 끼리라 느슨하다)
 *     -> CORS 가 실제로 필요해진다
 *   - 자산 URL 이 `MEDISCAN_PUBLIC_BASE` 로 만들어진다 -> **서명이 그 주소로 걸린다**
 *   - SPA 라우팅: `/cases/VS-SEG-202` 로 **직접 들어오면** 정적 서버가 404 를 낸다
 *     (dev 서버는 알아서 index.html 로 보내준다)
 *
 * 마지막 항목이 특히 배포 후에야 드러난다 — 새로고침하면 화면이 사라진다.
 *
 * 사용:
 *   node tools/staging/serve-dist.mjs [포트] [dist경로]
 */
import { createReadStream, existsSync, statSync } from 'node:fs'
import { createServer } from 'node:http'
import { extname, join, normalize, resolve } from 'node:path'

const PORT = Number(process.argv[2] ?? 4173)
const DIST = resolve(process.argv[3] ?? 'frontend/dist')

if (!existsSync(join(DIST, 'index.html'))) {
  console.log(`빌드 결과가 없습니다: ${DIST}`)
  console.log('  cd frontend && VITE_API_BASE=<주소> npm run build')
  process.exit(1)
}

const TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.woff2': 'font/woff2',
  '.woff': 'font/woff',
  '.ico': 'image/x-icon',
}

const server = createServer((req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`)
  // 경로 조작으로 dist 밖을 읽지 못하게 한다 (정적 호스팅도 이걸 막는다)
  const relative = normalize(decodeURIComponent(url.pathname)).replace(/^(\.\.[/\\])+/, '')
  let filePath = join(DIST, relative)

  const isFile = existsSync(filePath) && statSync(filePath).isFile()
  if (!isFile) {
    // SPA fallback — `/cases/VS-SEG-202` 로 직접 들어와도 앱이 뜬다.
    // **정적 호스팅에서 이 설정을 빠뜨리면 새로고침할 때마다 404 가 난다.**
    filePath = join(DIST, 'index.html')
  }
  if (!filePath.startsWith(DIST)) {
    res.writeHead(403).end('forbidden')
    return
  }

  res.writeHead(200, {
    'Content-Type': TYPES[extname(filePath)] ?? 'application/octet-stream',
    // 배포와 비슷하게: 해시가 붙은 자산은 오래, index.html 은 캐시하지 않는다
    'Cache-Control': filePath.endsWith('index.html')
      ? 'no-cache'
      : 'public, max-age=31536000, immutable',
  })
  createReadStream(filePath).pipe(res)
})

server.listen(PORT, () => {
  console.log(`dist 정적 서버: http://localhost:${PORT}  (${DIST})`)
  console.log('  SPA fallback 켜짐 — 실제 정적 호스팅에도 같은 설정이 필요하다')
})
