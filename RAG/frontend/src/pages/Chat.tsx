import React, {
  useState,
  useRef,
  useEffect,
  useCallback,
  KeyboardEvent,
} from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import {
  listSessions,
  createSession,
  deleteSession,
  getHistory,
  streamQueryWithStoredToken,
  Session,
  Message,
  Source,
  JudgeScores,
  UsageSummary,
} from '../api/chat'
import { listTags } from '../api/collections'
import { listDocuments } from '../api/documents'

// ─── Sub-components ───────────────────────────────────────────────────────────

function Spinner({ size = 4 }: { size?: number }) {
  return (
    <div
      className={`h-${size} w-${size} animate-spin rounded-full border-2 border-gray-600 border-t-blue-500`}
    />
  )
}

function StatusBadge({ score, label }: { score: number; label: string }) {
  const color =
    score >= 0.8
      ? 'bg-green-900/50 text-green-300 border-green-700'
      : score >= 0.5
      ? 'bg-yellow-900/50 text-yellow-300 border-yellow-700'
      : 'bg-red-900/50 text-red-300 border-red-700'

  return (
    <span className={`inline-flex items-center rounded px-1.5 py-0.5 text-xs border ${color}`}>
      {label}: {Math.round(score * 100)}%
    </span>
  )
}

function JudgePanel({ scores }: { scores: JudgeScores }) {
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      <StatusBadge score={scores.groundedness} label="Ground" />
      <StatusBadge score={scores.completeness} label="Complete" />
      <StatusBadge score={scores.relevance} label="Relevant" />
    </div>
  )
}

function SourcesPanel({ sources }: { sources: Source[] }) {
  const [open, setOpen] = useState(true)

  if (sources.length === 0) return null

  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs text-blue-400 hover:text-blue-300 transition-colors"
      >
        <svg
          className={`h-3.5 w-3.5 transition-transform ${open ? 'rotate-90' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
        </svg>
        {sources.length} source{sources.length !== 1 ? 's' : ''}
      </button>

      {open && (
        <ul className="mt-2 space-y-1.5">
          {sources.map((src, i) => (
            <li
              key={i}
              className="rounded-md bg-gray-700/50 px-3 py-2 text-xs text-gray-300 border border-gray-600"
            >
              <span className="font-medium text-gray-200">{src.document}</span>
              {src.section && (
                <span className="text-gray-400"> › {src.section}</span>
              )}
              {src.page !== null && (
                <span className="ml-2 text-gray-500">p.{src.page}</span>
              )}
              <span className="ml-2 text-gray-600">#{src.chunk_id}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

const PROVIDER_LABEL: Record<string, string> = {
  openrouter: 'OpenRouter',
  ollama: 'Ollama (local)',
}

function UsagePanel({ usage }: { usage: UsageSummary }) {
  const [open, setOpen] = useState(false)
  if (usage.calls.length === 0) return null

  const providerCounts = usage.calls.reduce<Record<string, number>>((acc, c) => {
    acc[c.provider] = (acc[c.provider] ?? 0) + 1
    return acc
  }, {})
  const providerSummary = Object.entries(providerCounts)
    .map(([p, n]) => `${PROVIDER_LABEL[p] ?? p}×${n}`)
    .join(', ')
  const costLabel = usage.total_cost_usd > 0 ? `$${usage.total_cost_usd.toFixed(4)}` : '$0 (local/free)'

  return (
    <div className="mt-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-300 transition-colors"
      >
        <svg
          className={`h-3 w-3 transition-transform ${open ? 'rotate-90' : ''}`}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
        </svg>
        {usage.calls.length} wywołań · {costLabel} · {providerSummary} · {usage.total_tokens_in + usage.total_tokens_out} tok.
      </button>

      {open && (
        <ul className="mt-2 space-y-1">
          {usage.calls.map((c, i) => (
            <li
              key={i}
              className="rounded-md bg-gray-700/50 px-3 py-1.5 text-xs text-gray-400 border border-gray-600 flex justify-between gap-3"
            >
              <span>
                <span className="text-gray-300 font-medium">{c.call_type}</span>
                {' · '}
                {PROVIDER_LABEL[c.provider] ?? c.provider}
                {c.model && <span className="text-gray-500"> ({c.model})</span>}
              </span>
              <span className="whitespace-nowrap">
                ↑{c.tokens_in} ↓{c.tokens_out}
                {c.cost_usd > 0 && <span className="ml-2 text-gray-300">${c.cost_usd.toFixed(5)}</span>}
                <span className="ml-2 text-gray-600">{c.latency_ms}ms</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

interface ChatMessageProps {
  message: Message
}

function ChatMessage({ message }: ChatMessageProps) {
  const isUser = message.role === 'user'

  return (
    <div className={`flex gap-3 ${isUser ? 'justify-end' : 'justify-start'}`}>
      {!isUser && (
        <div className="flex-shrink-0 flex h-8 w-8 items-center justify-center rounded-full bg-blue-600 mt-1">
          <svg className="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
          </svg>
        </div>
      )}

      <div className={`max-w-[75%] ${isUser ? 'order-first' : ''}`}>
        <div
          className={`rounded-2xl px-4 py-3 text-sm ${
            isUser
              ? 'bg-blue-600 text-white rounded-tr-sm'
              : 'bg-gray-800 text-gray-100 border border-gray-700 rounded-tl-sm'
          }`}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap">{message.content}</p>
          ) : (
            <div className="prose-dark">
              <ReactMarkdown>{message.content}</ReactMarkdown>
            </div>
          )}
        </div>

        {!isUser && message.sources && message.sources.length > 0 && (
          <SourcesPanel sources={message.sources} />
        )}
        {!isUser && message.judge_scores && (
          <JudgePanel scores={message.judge_scores} />
        )}
        {!isUser && message.usage && (
          <UsagePanel usage={message.usage} />
        )}
      </div>

      {isUser && (
        <div className="flex-shrink-0 flex h-8 w-8 items-center justify-center rounded-full bg-gray-600 mt-1">
          <svg className="h-4 w-4 text-gray-300" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 6a3.75 3.75 0 11-7.5 0 3.75 3.75 0 017.5 0zM4.501 20.118a7.5 7.5 0 0114.998 0A17.933 17.933 0 0112 21.75c-2.676 0-5.216-.584-7.499-1.632z" />
          </svg>
        </div>
      )}
    </div>
  )
}

// ─── Streaming message bubble ─────────────────────────────────────────────────

interface StreamingMessageProps {
  content: string
  sources: Source[]
  judgeScores: JudgeScores | null
  usage: UsageSummary | null
  isFinished: boolean
}

function StreamingMessage({ content, sources, judgeScores, usage, isFinished }: StreamingMessageProps) {
  return (
    <div className="flex gap-3 justify-start">
      <div className="flex-shrink-0 flex h-8 w-8 items-center justify-center rounded-full bg-blue-600 mt-1">
        <svg className="h-4 w-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
        </svg>
      </div>

      <div className="max-w-[75%]">
        <div className="rounded-2xl rounded-tl-sm bg-gray-800 border border-gray-700 px-4 py-3 text-sm text-gray-100">
          {content ? (
            <div className="prose-dark">
              <ReactMarkdown>{content}</ReactMarkdown>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-gray-500">
              <Spinner size={4} />
              <span className="text-xs">Thinking...</span>
            </div>
          )}
          {!isFinished && content && (
            <span className="inline-block h-3.5 w-0.5 bg-blue-400 animate-pulse ml-0.5 align-middle" />
          )}
        </div>

        {isFinished && sources.length > 0 && (
          <SourcesPanel sources={sources} />
        )}
        {isFinished && judgeScores && (
          <JudgePanel scores={judgeScores} />
        )}
        {isFinished && usage && (
          <UsagePanel usage={usage} />
        )}
      </div>
    </div>
  )
}

// ─── Session list item ────────────────────────────────────────────────────────

interface SessionItemProps {
  session: Session
  active: boolean
  onSelect: (id: number) => void
  onDelete: (id: number) => void
}

function SessionItem({ session, active, onSelect, onDelete }: SessionItemProps) {
  return (
    <div
      className={`group flex items-center gap-2 rounded-md px-3 py-2 cursor-pointer transition-colors ${
        active ? 'bg-gray-700 text-gray-100' : 'hover:bg-gray-700/50 text-gray-400 hover:text-gray-200'
      }`}
      onClick={() => onSelect(session.id)}
    >
      <svg className="h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 20.25c4.97 0 9-3.694 9-8.25s-4.03-8.25-9-8.25S3 7.444 3 12c0 2.104.859 4.023 2.273 5.48.432.447.74 1.04.586 1.641a4.483 4.483 0 01-.923 1.785A5.969 5.969 0 006 21c1.282 0 2.47-.402 3.445-1.087.81.22 1.668.337 2.555.337z" />
      </svg>
      <span className="flex-1 truncate text-sm">
        {session.title || `Session ${session.id}`}
      </span>
      {session.message_count > 0 && (
        <span className="text-xs text-gray-600 group-hover:hidden">{session.message_count}</span>
      )}
      <button
        onClick={(e) => {
          e.stopPropagation()
          onDelete(session.id)
        }}
        className="hidden group-hover:flex items-center text-gray-500 hover:text-red-400 transition-colors"
        title="Delete session"
      >
        <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  )
}

// ─── Main Chat Page ───────────────────────────────────────────────────────────

interface StreamingState {
  content: string
  sources: Source[]
  judgeScores: JudgeScores | null
  usage: UsageSummary | null
  isStreaming: boolean
  error: string | null
}

const INITIAL_STREAMING: StreamingState = {
  content: '',
  sources: [],
  judgeScores: null,
  usage: null,
  isStreaming: false,
  error: null,
}

export default function Chat() {
  const { chatId: chatIdParam } = useParams<{ chatId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const currentChatId = chatIdParam ? parseInt(chatIdParam, 10) : null

  const [query, setQuery] = useState('')
  const [streaming, setStreaming] = useState<StreamingState>(INITIAL_STREAMING)
  const [messages, setMessages] = useState<Message[]>([])
  const [selectedTagIds, setSelectedTagIds] = useState<number[]>([])
  const [selectedDocIds, setSelectedDocIds] = useState<number[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const streamAbortRef = useRef<boolean>(false)

  // Fetch sessions list
  const { data: sessionsData, isLoading: loadingSessions } = useQuery({
    queryKey: ['sessions'],
    queryFn: () => listSessions(50),
  })

  // Fetch available tags for context selector
  const { data: tagsData } = useQuery({
    queryKey: ['tags'],
    queryFn: listTags,
  })
  const availableTags = tagsData ?? []

  // Fetch ready documents for document picker
  const { data: docsData } = useQuery({
    queryKey: ['documents-picker'],
    queryFn: () => listDocuments({ limit: 100, status: 'ready' }),
  })
  const availableDocs = (docsData?.documents ?? []).filter(d => (d.page_count ?? 0) > 0)

  const sessions = sessionsData?.sessions ?? []

  // Fetch chat history when chatId changes
  const { isLoading: loadingHistory, data: historyData } = useQuery({
    queryKey: ['history', currentChatId],
    queryFn: () => getHistory(currentChatId!),
    enabled: currentChatId !== null,
  })

  // Sync messages from history query
  useEffect(() => {
    if (historyData) {
      setMessages(historyData.messages)
    }
  }, [historyData])

  // Create new session mutation
  const createMutation = useMutation({
    mutationFn: ({ title, tagIds, docIds }: { title?: string; tagIds?: number[]; docIds?: number[] }) =>
      createSession(title, [], tagIds, docIds),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      navigate(`/chat/${data.id}`)
    },
  })

  // Delete session mutation
  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteSession(id),
    onSuccess: (_, deletedId) => {
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
      if (currentChatId === deletedId) {
        navigate('/chat')
        setMessages([])
      }
    },
  })

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streaming.content])

  // Clear messages when no chat selected
  useEffect(() => {
    if (!currentChatId) {
      setMessages([])
      setStreaming(INITIAL_STREAMING)
    }
  }, [currentChatId])

  const handleNewChat = useCallback(() => {
    createMutation.mutate({
      tagIds: selectedTagIds.length > 0 ? selectedTagIds : undefined,
      docIds: selectedDocIds.length > 0 ? selectedDocIds : undefined,
    })
  }, [createMutation, selectedTagIds, selectedDocIds])

  const toggleTag = useCallback((id: number) => {
    setSelectedTagIds(prev => prev.includes(id) ? prev.filter(t => t !== id) : [...prev, id])
  }, [])

  const toggleDoc = useCallback((id: number) => {
    setSelectedDocIds(prev => prev.includes(id) ? prev.filter(d => d !== id) : [...prev, id])
  }, [])

  const handleSend = useCallback(async () => {
    const trimmed = query.trim()
    if (!trimmed || streaming.isStreaming) return

    // If no chat selected, create one first
    if (!currentChatId) {
      try {
        const session = await createSession(
          trimmed.slice(0, 60),
          [],
          selectedTagIds.length > 0 ? selectedTagIds : undefined,
          selectedDocIds.length > 0 ? selectedDocIds : undefined,
        )
        queryClient.invalidateQueries({ queryKey: ['sessions'] })
        navigate(`/chat/${session.id}`)
        return
      } catch {
        return
      }
    }

    const userMessage: Message = {
      id: Date.now(),
      role: 'user',
      content: trimmed,
      created_at: new Date().toISOString(),
    }

    setMessages((prev) => [...prev, userMessage])
    setQuery('')
    setStreaming({ content: '', sources: [], judgeScores: null, usage: null, isStreaming: true, error: null })
    streamAbortRef.current = false

    // Resize textarea
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }

    let accContent = ''
    let accSources: Source[] = []
    let accJudge: JudgeScores | null = null
    let accUsage: UsageSummary | null = null

    try {
      for await (const event of streamQueryWithStoredToken(currentChatId, trimmed)) {
        if (streamAbortRef.current) break

        if (event.type === 'token') {
          accContent += event.content
          setStreaming((prev) => ({ ...prev, content: accContent }))
        } else if (event.type === 'sources') {
          accSources = event.sources
          setStreaming((prev) => ({ ...prev, sources: accSources }))
        } else if (event.type === 'judge') {
          accJudge = {
            groundedness: event.groundedness,
            completeness: event.completeness,
            relevance: event.relevance,
          }
          setStreaming((prev) => ({ ...prev, judgeScores: accJudge }))
        } else if (event.type === 'usage') {
          accUsage = {
            calls: event.calls,
            total_cost_usd: event.total_cost_usd,
            total_tokens_in: event.total_tokens_in,
            total_tokens_out: event.total_tokens_out,
          }
          setStreaming((prev) => ({ ...prev, usage: accUsage }))
        } else if (event.type === 'done') {
          break
        } else if (event.type === 'error') {
          setStreaming((prev) => ({ ...prev, error: event.content, isStreaming: false }))
          return
        }
      }

      // Finalize: add assistant message to messages array
      const assistantMessage: Message = {
        id: Date.now() + 1,
        role: 'assistant',
        content: accContent,
        sources: accSources,
        judge_scores: accJudge ?? undefined,
        usage: accUsage ?? undefined,
        created_at: new Date().toISOString(),
      }

      setMessages((prev) => [...prev, assistantMessage])
      setStreaming(INITIAL_STREAMING)
      queryClient.invalidateQueries({ queryKey: ['sessions'] })
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Stream error'
      setStreaming((prev) => ({ ...prev, error: msg, isStreaming: false }))
    }
  }, [query, streaming.isStreaming, currentChatId, navigate, queryClient])

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setQuery(e.target.value)
    // Auto-resize
    e.target.style.height = 'auto'
    e.target.style.height = Math.min(e.target.scrollHeight, 160) + 'px'
  }

  const isEmpty = messages.length === 0 && !streaming.isStreaming

  return (
    <div className="flex h-full">
      {/* Sessions sidebar */}
      <div className="flex w-56 flex-shrink-0 flex-col border-r border-gray-700 bg-gray-800/50">
        <div className="flex items-center justify-between px-3 py-3 border-b border-gray-700">
          <span className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
            Conversations
          </span>
          <button
            onClick={handleNewChat}
            disabled={createMutation.isPending}
            className="rounded p-1 text-gray-400 hover:bg-gray-700 hover:text-gray-200 transition-colors"
            title="New conversation"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
            </svg>
          </button>
        </div>

        {/* Context (tag) filter */}
        {availableTags.length > 0 && (
          <div className="px-3 py-2 border-b border-gray-700">
            <p className="text-xs text-gray-500 mb-1.5">Search in:</p>
            <div className="flex flex-wrap gap-1">
              {availableTags.map(tag => {
                const active = selectedTagIds.includes(tag.id)
                return (
                  <button
                    key={tag.id}
                    onClick={() => toggleTag(tag.id)}
                    className={`rounded-full px-2 py-0.5 text-xs font-medium transition-colors ${
                      active
                        ? 'bg-blue-600 text-white'
                        : 'bg-gray-700 text-gray-400 hover:bg-gray-600 hover:text-gray-200'
                    }`}
                    title={active ? 'Click to remove filter' : 'Click to filter by this tag'}
                  >
                    {tag.name}
                  </button>
                )
              })}
            </div>
            {selectedTagIds.length > 0 && (
              <p className="text-xs text-blue-400 mt-1">
                New chats will search only in selected tags
              </p>
            )}
          </div>
        )}

        {/* Document picker */}
        {availableDocs.length > 0 && (
          <div className="px-3 py-2 border-b border-gray-700">
            <p className="text-xs text-gray-500 mb-1.5">Or pick document(s):</p>
            <div className="space-y-0.5 max-h-36 overflow-y-auto">
              {availableDocs.map(doc => {
                const active = selectedDocIds.includes(doc.id)
                const icon = doc.source_type === 'youtube' ? '▶' : doc.file_type === 'mp3' || doc.file_type === 'audio' ? '🎵' : doc.file_type === 'pdf' ? '📄' : '📝'
                return (
                  <button
                    key={doc.id}
                    onClick={() => toggleDoc(doc.id)}
                    className={`w-full text-left rounded px-2 py-1 text-xs transition-colors flex items-center gap-1.5 ${
                      active
                        ? 'bg-blue-600 text-white'
                        : 'text-gray-400 hover:bg-gray-700 hover:text-gray-200'
                    }`}
                    title={doc.filename}
                  >
                    <span className="flex-shrink-0">{icon}</span>
                    <span className="truncate">{doc.filename.replace(/^https?:\/\//, '')}</span>
                  </button>
                )
              })}
            </div>
            {selectedDocIds.length > 0 && (
              <p className="text-xs text-blue-400 mt-1">
                {selectedDocIds.length} doc{selectedDocIds.length > 1 ? 's' : ''} selected
              </p>
            )}
          </div>
        )}

        <div className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5">
          {loadingSessions ? (
            <div className="flex justify-center py-4">
              <Spinner />
            </div>
          ) : sessions.length === 0 ? (
            <p className="px-3 py-4 text-xs text-gray-600 text-center">No conversations yet</p>
          ) : (
            sessions.map((s) => (
              <SessionItem
                key={s.id}
                session={s}
                active={s.id === currentChatId}
                onSelect={(id) => {
                  if (id !== currentChatId) {
                    setStreaming(INITIAL_STREAMING)
                    navigate(`/chat/${id}`)
                  }
                }}
                onDelete={(id) => deleteMutation.mutate(id)}
              />
            ))
          )}
        </div>
      </div>

      {/* Chat area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Header */}
        <div className="flex h-14 items-center border-b border-gray-700 px-6">
          <h2 className="text-sm font-semibold text-gray-200">
            {currentChatId
              ? sessions.find((s) => s.id === currentChatId)?.title ||
                `Session ${currentChatId}`
              : 'New Conversation'}
          </h2>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-5">
          {loadingHistory ? (
            <div className="flex justify-center py-8">
              <Spinner size={6} />
            </div>
          ) : isEmpty ? (
            <div className="flex flex-col items-center justify-center h-full text-center gap-4 pb-10">
              <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-gray-800 border border-gray-700">
                <svg className="h-8 w-8 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
                </svg>
              </div>
              <div>
                <p className="text-gray-300 font-medium">Ask anything</p>
                <p className="text-sm text-gray-500 mt-1">
                  {currentChatId
                    ? 'Start by typing your question below'
                    : 'Select or create a conversation to get started'}
                </p>
              </div>
            </div>
          ) : (
            <>
              {messages.map((msg) => (
                <ChatMessage key={msg.id} message={msg} />
              ))}
              {streaming.isStreaming && (
                <StreamingMessage
                  content={streaming.content}
                  sources={streaming.sources}
                  judgeScores={streaming.judgeScores}
                  usage={streaming.usage}
                  isFinished={false}
                />
              )}
              {streaming.error && (
                <div className="rounded-lg bg-red-900/30 border border-red-700 px-4 py-3 text-sm text-red-300">
                  Error: {streaming.error}
                </div>
              )}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* Input area */}
        <div className="border-t border-gray-700 p-4">
          <div className="flex items-end gap-3 rounded-xl bg-gray-800 border border-gray-600 px-4 py-3 focus-within:border-blue-500 focus-within:ring-1 focus-within:ring-blue-500 transition-all">
            <textarea
              ref={textareaRef}
              value={query}
              onChange={handleTextareaChange}
              onKeyDown={handleKeyDown}
              placeholder={
                currentChatId
                  ? 'Ask a question... (Enter to send, Shift+Enter for new line)'
                  : 'Type to start a new conversation...'
              }
              rows={1}
              disabled={streaming.isStreaming}
              className="flex-1 resize-none bg-transparent text-sm text-gray-100 placeholder-gray-500 outline-none disabled:opacity-50"
              style={{ maxHeight: '160px', overflowY: 'auto' }}
            />
            <button
              onClick={handleSend}
              disabled={streaming.isStreaming || !query.trim()}
              className="flex-shrink-0 flex h-8 w-8 items-center justify-center rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              title="Send message"
            >
              {streaming.isStreaming ? (
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              ) : (
                <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
                </svg>
              )}
            </button>
          </div>
          <p className="mt-1.5 text-xs text-gray-600 text-center">
            RAG responses are grounded in your documents
          </p>
        </div>
      </div>
    </div>
  )
}
