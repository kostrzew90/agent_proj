import { useState, useRef, useCallback, DragEvent } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listDocuments,
  uploadDocument,
  deleteDocument,
  crawlUrl,
  ingestYoutube,
  DocumentItem,
} from '../api/documents'

// ─── Helpers ──────────────────────────────────────────────────────────────────

function formatBytes(bytes: number | null): string {
  if (bytes === null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: DocumentItem['status'] }) {
  const styles: Record<DocumentItem['status'], string> = {
    pending: 'bg-gray-700 text-gray-300 border-gray-600',
    processing: 'bg-blue-900/50 text-blue-300 border-blue-700',
    ready: 'bg-green-900/50 text-green-300 border-green-700',
    error: 'bg-red-900/50 text-red-300 border-red-700',
  }

  const icons: Record<DocumentItem['status'], string> = {
    pending: '◷',
    processing: '⟳',
    ready: '✓',
    error: '✗',
  }

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${styles[status]}`}
    >
      <span>{icons[status]}</span>
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  )
}

// ─── File type icon ───────────────────────────────────────────────────────────

function FileTypeIcon({ type }: { type: string }) {
  const color =
    type === 'pdf'
      ? 'text-red-400'
      : type === 'docx' || type === 'doc'
      ? 'text-blue-400'
      : type === 'markdown' || type === 'txt'
      ? 'text-gray-300'
      : type === 'image'
      ? 'text-purple-400'
      : 'text-gray-400'

  return (
    <span className={`text-xs font-mono font-semibold uppercase ${color}`}>
      {type.slice(0, 4)}
    </span>
  )
}

// ─── Upload zone ──────────────────────────────────────────────────────────────

interface UploadZoneProps {
  onFiles: (files: File[]) => void
  uploading: boolean
}

function UploadZone({ onFiles, uploading }: UploadZoneProps) {
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const handleDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault()
      setDragging(false)
      const files = Array.from(e.dataTransfer.files)
      if (files.length > 0) onFiles(files)
    },
    [onFiles],
  )

  const handleDragOver = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    setDragging(true)
  }

  const handleDragLeave = () => setDragging(false)

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (files.length > 0) onFiles(files)
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <div
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onClick={() => !uploading && inputRef.current?.click()}
      className={`relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed py-10 transition-colors cursor-pointer ${
        dragging
          ? 'border-blue-400 bg-blue-900/20'
          : uploading
          ? 'border-gray-600 bg-gray-800/50 cursor-not-allowed'
          : 'border-gray-600 bg-gray-800/30 hover:border-gray-500 hover:bg-gray-800/50'
      }`}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        className="hidden"
        onChange={handleChange}
        disabled={uploading}
        accept=".pdf,.docx,.doc,.txt,.md,.csv,.rtf,.pptx,.xlsx,.png,.jpg,.jpeg,.tiff,.bmp,.mp3,.wav,.m4a,.ogg,.flac,.mp4,.mkv,.avi,.mov,.webm"
      />

      {uploading ? (
        <>
          <div className="h-10 w-10 animate-spin rounded-full border-2 border-gray-600 border-t-blue-500 mb-3" />
          <p className="text-sm text-gray-400">Uploading...</p>
        </>
      ) : (
        <>
          <svg
            className={`h-10 w-10 mb-3 ${dragging ? 'text-blue-400' : 'text-gray-500'}`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5"
            />
          </svg>
          <p className="text-sm font-medium text-gray-300">
            {dragging ? 'Drop files here' : 'Drag & drop files, or click to browse'}
          </p>
          <p className="text-xs text-gray-500 mt-1">
            PDF, DOCX, TXT, MD, CSV, PPTX, images — MP4, MP3, WAV, M4A and more
          </p>
        </>
      )}
    </div>
  )
}

// ─── Crawl section ────────────────────────────────────────────────────────────

interface CrawlSectionProps {
  onCrawl: (url: string, depth: number) => void
  crawling: boolean
  error: string | null
}

function CrawlSection({ onCrawl, crawling, error }: CrawlSectionProps) {
  const [url, setUrl] = useState('')
  const [depth, setDepth] = useState(1)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (url.trim()) {
      onCrawl(url.trim(), depth)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card">
      <h3 className="text-sm font-semibold text-gray-300 mb-3">Crawl Web URL</h3>

      {error && (
        <div className="mb-3 rounded-md bg-red-900/30 border border-red-700 px-3 py-2 text-xs text-red-300">
          {error}
        </div>
      )}

      <div className="flex gap-3">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://example.com/article"
          className="input-field flex-1"
          disabled={crawling}
          required
        />

        <select
          value={depth}
          onChange={(e) => setDepth(Number(e.target.value))}
          className="input-field w-28"
          disabled={crawling}
          title="Crawl depth"
        >
          <option value={1}>Depth 1</option>
          <option value={2}>Depth 2</option>
          <option value={3}>Depth 3</option>
        </select>

        <button
          type="submit"
          disabled={crawling || !url.trim()}
          className="btn-primary whitespace-nowrap"
        >
          {crawling ? (
            <span className="flex items-center gap-2">
              <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              Crawling...
            </span>
          ) : (
            'Crawl'
          )}
        </button>
      </div>
    </form>
  )
}

// ─── YouTube section ──────────────────────────────────────────────────────────

interface YouTubeSectionProps {
  onIngest: (url: string) => void
  ingesting: boolean
  error: string | null
}

function YouTubeSection({ onIngest, ingesting, error }: YouTubeSectionProps) {
  const [url, setUrl] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (url.trim()) {
      onIngest(url.trim())
      setUrl('')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="card">
      <h3 className="text-sm font-semibold text-gray-300 mb-1 flex items-center gap-2">
        <svg className="h-4 w-4 text-red-500" viewBox="0 0 24 24" fill="currentColor">
          <path d="M23.498 6.186a3.016 3.016 0 00-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 00.502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 002.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 002.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814zM9.545 15.568V8.432L15.818 12l-6.273 3.568z"/>
        </svg>
        YouTube Transcript
      </h3>
      <p className="text-xs text-gray-500 mb-3">
        Automatically fetches subtitles (PL/EN) and indexes them for chat.
      </p>

      {error && (
        <div className="mb-3 rounded-md bg-red-900/30 border border-red-700 px-3 py-2 text-xs text-red-300">
          {error}
        </div>
      )}

      <div className="flex gap-3">
        <input
          type="url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://www.youtube.com/watch?v=..."
          className="input-field flex-1"
          disabled={ingesting}
          required
        />
        <button
          type="submit"
          disabled={ingesting || !url.trim()}
          className="btn-primary whitespace-nowrap"
        >
          {ingesting ? (
            <span className="flex items-center gap-2">
              <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white/30 border-t-white" />
              Fetching...
            </span>
          ) : (
            'Add video'
          )}
        </button>
      </div>
    </form>
  )
}

// ─── Document row ─────────────────────────────────────────────────────────────

interface DocumentRowProps {
  doc: DocumentItem
  onDelete: (id: number) => void
  deleting: boolean
}

function stepLabel(progress: number, taskType: string): string {
  if (taskType === 'youtube') {
    if (progress < 0.2) return 'Fetching transcript…'
    if (progress < 0.4) return 'Parsing subtitles…'
    if (progress < 0.6) return 'Chunking…'
    if (progress < 0.9) return 'Embedding chunks…'
    return 'Saving…'
  }
  if (progress < 0.4) return 'Parsing document…'
  if (progress < 0.7) return 'Chunking…'
  if (progress < 0.95) return 'Embedding…'
  return 'Saving…'
}

function DocumentRow({ doc, onDelete, deleting }: DocumentRowProps) {
  const isActive = doc.status === 'pending' || doc.status === 'processing' ||
    (doc.task_status === 'running')
  const progress = doc.task_progress ?? 0
  const pct = Math.round(progress * 100)

  return (
    <tr className="border-t border-gray-700 hover:bg-gray-800/50 transition-colors">
      <td className="px-4 py-3">
        <div className="flex items-center gap-3">
          <FileTypeIcon type={doc.file_type} />
          <div className="min-w-0 flex-1">
            <p className="text-sm text-gray-200 truncate max-w-xs" title={doc.filename}>
              {doc.filename}
            </p>
            {doc.source_url && (
              <a
                href={doc.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs text-blue-400 hover:text-blue-300 truncate max-w-xs block"
                title={doc.source_url}
              >
                {doc.source_url}
              </a>
            )}
            {isActive && doc.task_type && (
              <div className="mt-1.5 max-w-xs">
                <div className="flex justify-between text-xs text-gray-500 mb-0.5">
                  <span>{stepLabel(progress, doc.task_type)}</span>
                  <span>{pct}%</span>
                </div>
                <div className="h-1 w-full rounded-full bg-gray-700">
                  <div
                    className="h-1 rounded-full bg-blue-500 transition-all duration-500"
                    style={{ width: `${Math.max(pct, 3)}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      </td>
      <td className="px-4 py-3 text-sm text-gray-400">{formatBytes(doc.file_size)}</td>
      <td className="px-4 py-3">
        <StatusBadge status={doc.status} />
      </td>
      <td className="px-4 py-3 text-sm text-gray-500">{formatDate(doc.created_at)}</td>
      <td className="px-4 py-3">
        <button
          onClick={() => onDelete(doc.id)}
          disabled={deleting}
          className="text-gray-500 hover:text-red-400 transition-colors disabled:opacity-40"
          title="Delete document"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
          </svg>
        </button>
      </td>
    </tr>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Documents() {
  const queryClient = useQueryClient()
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [crawlError, setCrawlError] = useState<string | null>(null)
  const [youtubeError, setYoutubeError] = useState<string | null>(null)
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['documents'],
    queryFn: () => listDocuments({ limit: 100 }),
    refetchInterval: 5000, // Poll every 5s to update processing status
  })

  const uploadMutation = useMutation({
    mutationFn: (file: File) => uploadDocument(file),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      setSuccessMsg('File uploaded and queued for processing')
      setTimeout(() => setSuccessMsg(null), 3000)
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : 'Upload failed'
      // Check for 409 duplicate
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const detail = (err as any)?.response?.data?.detail
      if (typeof detail === 'object' && detail?.message) {
        setUploadError(`Duplicate: "${detail.existing_filename}" already exists`)
      } else {
        setUploadError(typeof detail === 'string' ? detail : msg)
      }
      setTimeout(() => setUploadError(null), 5000)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (id: number) => deleteDocument(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
    },
  })

  const crawlMutation = useMutation({
    mutationFn: ({ url, depth }: { url: string; depth: number }) =>
      crawlUrl(url, depth),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      setSuccessMsg('Crawl started — document will appear when processing completes')
      setTimeout(() => setSuccessMsg(null), 4000)
    },
    onError: (err: unknown) => {
      const msg = err instanceof Error ? err.message : 'Crawl failed'
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const detail = (err as any)?.response?.data?.detail
      setCrawlError(typeof detail === 'string' ? detail : msg)
      setTimeout(() => setCrawlError(null), 5000)
    },
  })

  const handleFiles = useCallback(
    (files: File[]) => {
      setUploadError(null)
      // Upload sequentially
      files.forEach((file) => uploadMutation.mutate(file))
    },
    [uploadMutation],
  )

  const handleCrawl = useCallback(
    (url: string, depth: number) => {
      setCrawlError(null)
      crawlMutation.mutate({ url, depth })
    },
    [crawlMutation],
  )

  const youtubeMutation = useMutation({
    mutationFn: (url: string) => ingestYoutube(url),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      setSuccessMsg('YouTube transcript queued — will appear when processing completes')
      setTimeout(() => setSuccessMsg(null), 5000)
    },
    onError: (err: unknown) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const detail = (err as any)?.response?.data?.detail
      setYoutubeError(typeof detail === 'string' ? detail : 'Failed to add YouTube video')
      setTimeout(() => setYoutubeError(null), 5000)
    },
  })

  const handleYoutube = useCallback(
    (url: string) => {
      setYoutubeError(null)
      youtubeMutation.mutate(url)
    },
    [youtubeMutation],
  )

  const documents = data?.documents ?? []
  const total = data?.total ?? 0

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex h-14 items-center justify-between border-b border-gray-700 px-6">
        <div className="flex items-center gap-3">
          <h1 className="text-sm font-semibold text-gray-200">Documents</h1>
          {!isLoading && (
            <span className="rounded-full bg-gray-700 px-2 py-0.5 text-xs text-gray-400">
              {total}
            </span>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Success message */}
        {successMsg && (
          <div className="rounded-lg bg-green-900/30 border border-green-700 px-4 py-3 text-sm text-green-300">
            {successMsg}
          </div>
        )}

        {/* Upload zone */}
        <div>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Upload Files
          </h2>
          {uploadError && (
            <div className="mb-3 rounded-md bg-red-900/30 border border-red-700 px-3 py-2 text-sm text-red-300">
              {uploadError}
            </div>
          )}
          <UploadZone onFiles={handleFiles} uploading={uploadMutation.isPending} />
        </div>

        {/* YouTube section */}
        <div>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            YouTube
          </h2>
          <YouTubeSection
            onIngest={handleYoutube}
            ingesting={youtubeMutation.isPending}
            error={youtubeError}
          />
        </div>

        {/* Crawl section */}
        <div>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Web Crawl
          </h2>
          <CrawlSection
            onCrawl={handleCrawl}
            crawling={crawlMutation.isPending}
            error={crawlError}
          />
        </div>

        {/* Document list */}
        <div>
          <h2 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">
            Document Library
          </h2>

          {isLoading ? (
            <div className="flex justify-center py-12">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-gray-600 border-t-blue-500" />
            </div>
          ) : error ? (
            <div className="rounded-lg bg-red-900/30 border border-red-700 px-4 py-3 text-sm text-red-300">
              Failed to load documents
            </div>
          ) : documents.length === 0 ? (
            <div className="rounded-xl border border-gray-700 bg-gray-800/30 py-12 text-center">
              <svg
                className="mx-auto h-10 w-10 text-gray-600 mb-3"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
                strokeWidth={1.5}
              >
                <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
              </svg>
              <p className="text-sm text-gray-500">No documents yet. Upload one above.</p>
            </div>
          ) : (
            <div className="overflow-hidden rounded-xl border border-gray-700">
              <table className="w-full">
                <thead className="bg-gray-800">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">
                      File
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">
                      Size
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">
                      Status
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-400 uppercase tracking-wide">
                      Uploaded
                    </th>
                    <th className="px-4 py-3 w-10" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-700/50">
                  {documents.map((doc) => (
                    <DocumentRow
                      key={doc.id}
                      doc={doc}
                      onDelete={(id) => deleteMutation.mutate(id)}
                      deleting={deleteMutation.isPending}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
