import { useState, useEffect } from 'react'
import { fetchPatterns, reviewPattern } from '../api/client'

export function MemoryView() {
  const [patterns, setPatterns] = useState<any[]>([])

  const load = () => fetchPatterns().then(setPatterns).catch(() => {})
  useEffect(() => { load() }, [])

  const handleReview = async (id: number, action: 'approve' | 'reject') => {
    await reviewPattern(id, action)
    load()
  }

  return (
    <div className="p-4 space-y-3 overflow-y-auto">
      <h3 className="font-bold text-sm text-gray-400 uppercase">Learned Patterns</h3>
      {patterns.map(p => (
        <div key={p.id} className={`p-3 rounded border ${
          p.needs_review ? 'border-yellow-600 bg-yellow-900/20' :
          p.verified ? 'border-green-600 bg-green-900/20' : 'border-gray-700 bg-gray-800'
        }`}>
          <div className="text-sm font-mono">{p.pattern}</div>
          <div className="text-xs text-gray-400 mt-1">{p.solution}</div>
          <div className="flex gap-2 mt-2 text-xs text-gray-500">
            <span>conf: {p.confidence?.toFixed(2)}</span>
            <span>applied: {p.times_applied}</span>
            <span>failed: {p.times_failed}</span>
            <span>src: {p.source}</span>
            {p.verified && <span className="text-green-400">verified</span>}
          </div>
          {p.needs_review && (
            <div className="flex gap-2 mt-2">
              <button onClick={() => handleReview(p.id, 'approve')}
                className="px-2 py-1 bg-green-700 rounded text-xs hover:bg-green-600">Approve</button>
              <button onClick={() => handleReview(p.id, 'reject')}
                className="px-2 py-1 bg-red-700 rounded text-xs hover:bg-red-600">Reject</button>
            </div>
          )}
        </div>
      ))}
      {patterns.length === 0 && <div className="text-gray-500 text-sm">No patterns yet</div>}
    </div>
  )
}
