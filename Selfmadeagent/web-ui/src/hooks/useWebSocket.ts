import { useEffect, useRef, useState, useCallback } from 'react'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

export function useWebSocket(sessionId: string | null) {
  const ws = useRef<WebSocket | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    if (!sessionId) return

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/ws/${sessionId}`
    const socket = new WebSocket(url)

    socket.onopen = () => setConnected(true)
    socket.onclose = () => setConnected(false)

    socket.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.type === 'response') {
        // Remove any pending status messages and add final response
        setMessages(prev => [
          ...prev.filter(m => !m.content.startsWith('[status]') && !m.content.startsWith('[tool]')),
          {
            role: 'assistant',
            content: data.content,
            timestamp: new Date().toISOString(),
          }
        ])
      } else if (data.type === 'status') {
        setMessages(prev => {
          const filtered = prev.filter(m => !m.content.startsWith('[status]'))
          return [...filtered, {
            role: 'assistant',
            content: `[status] ${data.text}`,
            timestamp: new Date().toISOString(),
          }]
        })
      } else if (data.type === 'tool_start') {
        setMessages(prev => {
          const filtered = prev.filter(m => !m.content.startsWith('[status]'))
          return [...filtered, {
            role: 'assistant',
            content: `[tool] Running ${data.tool}(${Object.values(data.args || {}).join(', ').slice(0, 80)})...`,
            timestamp: new Date().toISOString(),
          }]
        })
      } else if (data.type === 'tool_result') {
        setMessages(prev => [...prev, {
          role: 'assistant',
          content: `[tool] ${data.tool} ${data.score >= 0.7 ? 'OK' : 'WARN'}: ${(data.preview || '').slice(0, 120)}`,
          timestamp: new Date().toISOString(),
        }])
      }
    }

    ws.current = socket
    return () => { socket.close() }
  }, [sessionId])

  const send = useCallback((message: string) => {
    if (ws.current?.readyState === WebSocket.OPEN) {
      setMessages(prev => [...prev, {
        role: 'user',
        content: message,
        timestamp: new Date().toISOString(),
      }])
      ws.current.send(JSON.stringify({ message }))
    }
  }, [])

  return { messages, send, connected }
}
