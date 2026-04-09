const BASE = ''

export async function fetchTrace(sessionId: string) {
  const res = await fetch(`${BASE}/api/sessions/${sessionId}/trace`)
  return res.json()
}

export async function fetchPatterns() {
  const res = await fetch(`${BASE}/api/memory/patterns`)
  return res.json()
}

export async function reviewPattern(id: number, action: 'approve' | 'reject') {
  const res = await fetch(`${BASE}/api/memory/patterns/${id}/review?action=${action}`, { method: 'POST' })
  return res.json()
}

export async function fetchFacts() {
  const res = await fetch(`${BASE}/api/memory/facts`)
  return res.json()
}
