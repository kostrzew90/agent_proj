import { apiClient, getToken } from './client'

export interface Session {
  id: number
  title: string
  created_at: string
  message_count: number
}

export interface Message {
  id: number
  role: 'user' | 'assistant'
  content: string
  sources?: Source[]
  judge_scores?: JudgeScores
  usage?: UsageSummary
  created_at: string
}

export interface LlmCallRecord {
  call_type: string
  provider: string
  model: string | null
  tokens_in: number
  tokens_out: number
  cost_usd: number
  latency_ms: number
}

export interface UsageSummary {
  calls: LlmCallRecord[]
  total_cost_usd: number
  total_tokens_in: number
  total_tokens_out: number
}

export interface Source {
  document: string
  page: number | null
  section: string
  chunk_id: number
}

export interface JudgeScores {
  groundedness: number
  completeness: number
  relevance: number
}

export type SSEEvent =
  | { type: 'token'; content: string }
  | { type: 'sources'; sources: Source[] }
  | { type: 'judge'; groundedness: number; completeness: number; relevance: number }
  | ({ type: 'usage' } & UsageSummary)
  | { type: 'done' }
  | { type: 'error'; content: string }

export interface CreateSessionResponse {
  id: number
  title: string
  created_at: string
}

export async function createSession(
  title?: string,
  folderIds?: number[],
  tagIds?: number[],
  documentIds?: number[],
): Promise<CreateSessionResponse> {
  const { data } = await apiClient.post<CreateSessionResponse>('/chat/', {
    title: title ?? null,
    folder_ids: folderIds ?? [],
    tag_ids: tagIds ?? [],
    document_ids: documentIds ?? [],
  })
  return data
}

export async function listSessions(limit = 50): Promise<{ sessions: Session[] }> {
  const { data } = await apiClient.get<{ sessions: Session[] }>('/chat/', {
    params: { limit },
  })
  return data
}

export async function deleteSession(id: number): Promise<void> {
  await apiClient.delete(`/chat/${id}`)
}

export async function getHistory(chatId: number): Promise<{ messages: Message[] }> {
  const { data } = await apiClient.get<{ chat_id: number; messages: Message[] }>(
    `/chat/${chatId}/history`,
  )
  return { messages: data.messages }
}

export async function* streamQuery(
  chatId: number,
  query: string,
  token: string,
): AsyncGenerator<SSEEvent> {
  const response = await fetch(`/api/v1/chat/${chatId}/query`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({ query }),
  })

  if (!response.ok) {
    const errorText = await response.text()
    throw new Error(`HTTP ${response.status}: ${errorText}`)
  }

  if (!response.body) {
    throw new Error('Response body is null')
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      // Keep the last potentially incomplete line in the buffer
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed || !trimmed.startsWith('data:')) continue

        const jsonStr = trimmed.slice(5).trim()
        if (!jsonStr) continue

        try {
          const event = JSON.parse(jsonStr) as SSEEvent
          yield event
          if (event.type === 'done' || event.type === 'error') return
        } catch {
          // Ignore malformed JSON lines
        }
      }
    }

    // Process any remaining buffer content
    if (buffer.trim()) {
      const trimmed = buffer.trim()
      if (trimmed.startsWith('data:')) {
        const jsonStr = trimmed.slice(5).trim()
        if (jsonStr) {
          try {
            const event = JSON.parse(jsonStr) as SSEEvent
            yield event
          } catch {
            // Ignore
          }
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}

// Convenience wrapper that gets token from localStorage
export async function* streamQueryWithStoredToken(
  chatId: number,
  query: string,
): AsyncGenerator<SSEEvent> {
  const token = getToken()
  if (!token) {
    window.location.href = '/login'
    return
  }
  yield* streamQuery(chatId, query, token)
}
