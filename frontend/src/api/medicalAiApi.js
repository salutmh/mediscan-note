const API_BASE = import.meta.env.VITE_MEDICAL_AI_API_BASE || 'http://127.0.0.1:8000'

async function request(path) {
  const res = await fetch(`${API_BASE}${path}`)

  if (!res.ok) {
    const text = await res.text()
    throw new Error(`API ${res.status}: ${text}`)
  }

  return res.json()
}

export async function getAiCases() {
  return request('/api/cases')
}

export async function getAiCase(caseId) {
  return request(`/api/cases/${encodeURIComponent(caseId)}`)
}

export function assetUrl(path) {
  if (!path) return null
  if (path.startsWith('http://') || path.startsWith('https://')) return path
  return `${API_BASE}${path}`
}

export { API_BASE }
