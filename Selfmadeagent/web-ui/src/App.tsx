import { useState, useEffect } from 'react'
import { Chat } from './components/Chat'
import { DebugPanel } from './components/DebugPanel'

interface SessionInfo {
  id: string
  goal: string | null
  status: string
}

function App() {
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [activeSession, setActiveSession] = useState<string | null>(null)

  useEffect(() => {
    fetch('/sessions').then(r => r.json()).then(setSessions).catch(() => {})
  }, [])

  const createSession = async () => {
    const res = await fetch('/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: 'Hello' }),
    })
    const data = await res.json()
    setActiveSession(data.session_id)
    fetch('/sessions').then(r => r.json()).then(setSessions).catch(() => {})
  }

  return (
    <div className="flex h-screen bg-gray-900 text-white">
      {/* Sidebar */}
      <div className="w-56 border-r border-gray-700 p-4 flex flex-col">
        <h1 className="text-lg font-bold mb-4">Selfmadeagent</h1>
        <button onClick={createSession} className="mb-4 px-3 py-2 bg-blue-600 rounded hover:bg-blue-700 text-sm">
          + New Session
        </button>
        <div className="flex-1 overflow-y-auto space-y-1">
          {sessions.map(s => (
            <button
              key={s.id}
              onClick={() => setActiveSession(s.id)}
              className={`w-full text-left px-3 py-2 rounded text-sm truncate ${
                activeSession === s.id ? 'bg-gray-700' : 'hover:bg-gray-800'
              }`}
            >
              {s.goal?.slice(0, 30) || s.id.slice(0, 8)}
            </button>
          ))}
        </div>
      </div>

      {/* Chat + Debug */}
      {activeSession ? (
        <>
          <div className="flex-1">
            <Chat sessionId={activeSession} />
          </div>
          <div className="w-96">
            <DebugPanel sessionId={activeSession} />
          </div>
        </>
      ) : (
        <div className="flex-1 flex items-center justify-center text-gray-500">
          Select or create a session
        </div>
      )}
    </div>
  )
}

export default App
