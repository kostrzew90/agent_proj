import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  listFolders,
  listTags,
  createFolder,
  deleteFolder,
  createTag,
  deleteTag,
  Folder,
  Tag,
} from '../api/collections'

// ─── Color picker ─────────────────────────────────────────────────────────────

const PRESET_COLORS = [
  '#3B82F6', // blue
  '#10B981', // emerald
  '#F59E0B', // amber
  '#EF4444', // red
  '#8B5CF6', // violet
  '#EC4899', // pink
  '#06B6D4', // cyan
  '#F97316', // orange
]

interface ColorPickerProps {
  value: string
  onChange: (color: string) => void
}

function ColorPicker({ value, onChange }: ColorPickerProps) {
  return (
    <div className="flex gap-1.5 flex-wrap">
      {PRESET_COLORS.map((color) => (
        <button
          key={color}
          type="button"
          onClick={() => onChange(color)}
          className={`h-6 w-6 rounded-full transition-all ${
            value === color ? 'ring-2 ring-offset-2 ring-offset-gray-800 ring-white scale-110' : 'hover:scale-105'
          }`}
          style={{ backgroundColor: color }}
          title={color}
        />
      ))}
    </div>
  )
}

// ─── Folder item ──────────────────────────────────────────────────────────────

interface FolderItemProps {
  folder: Folder
  onDelete: (id: number) => void
  deleting: boolean
  depth?: number
}

function FolderItem({ folder, onDelete, deleting, depth = 0 }: FolderItemProps) {
  return (
    <>
      <div
        className="flex items-center justify-between rounded-md px-3 py-2 hover:bg-gray-700/50 group"
        style={{ paddingLeft: `${12 + depth * 20}px` }}
      >
        <div className="flex items-center gap-2 min-w-0">
          {depth > 0 && (
            <span className="text-gray-600 text-xs">└</span>
          )}
          <svg
            className="h-4 w-4 text-blue-400 flex-shrink-0"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z"
            />
          </svg>
          <span className="text-sm text-gray-200 truncate">{folder.name}</span>
          {folder.children.length > 0 && (
            <span className="text-xs text-gray-600">({folder.children.length})</span>
          )}
        </div>

        <button
          onClick={() => onDelete(folder.id)}
          disabled={deleting}
          className="hidden group-hover:flex items-center text-gray-500 hover:text-red-400 transition-colors disabled:opacity-40"
          title="Delete folder"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0" />
          </svg>
        </button>
      </div>

      {folder.children.map((child) => (
        <FolderItem
          key={child.id}
          folder={child}
          onDelete={onDelete}
          deleting={deleting}
          depth={depth + 1}
        />
      ))}
    </>
  )
}

// ─── Tag item ─────────────────────────────────────────────────────────────────

interface TagItemProps {
  tag: Tag
  onDelete: (id: number) => void
  deleting: boolean
}

function TagItem({ tag, onDelete, deleting }: TagItemProps) {
  return (
    <div className="flex items-center justify-between rounded-md px-3 py-2 hover:bg-gray-700/50 group">
      <div className="flex items-center gap-2.5">
        <div
          className="h-3 w-3 rounded-full flex-shrink-0"
          style={{ backgroundColor: tag.color }}
        />
        <span className="text-sm text-gray-200">{tag.name}</span>
        {tag.document_count > 0 && (
          <span className="rounded-full bg-gray-700 px-1.5 py-0.5 text-xs text-gray-400">
            {tag.document_count}
          </span>
        )}
      </div>

      <button
        onClick={() => onDelete(tag.id)}
        disabled={deleting}
        className="hidden group-hover:flex items-center text-gray-500 hover:text-red-400 transition-colors disabled:opacity-40"
        title="Delete tag"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
    </div>
  )
}

// ─── Create folder form ───────────────────────────────────────────────────────

interface CreateFolderFormProps {
  onSubmit: (name: string) => void
  loading: boolean
  error: string | null
}

function CreateFolderForm({ onSubmit, loading, error }: CreateFolderFormProps) {
  const [name, setName] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (name.trim()) {
      onSubmit(name.trim())
      setName('')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex gap-2 mt-3">
      <input
        type="text"
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Folder name"
        className="input-field flex-1"
        disabled={loading}
        maxLength={100}
      />
      <button
        type="submit"
        disabled={loading || !name.trim()}
        className="btn-primary"
      >
        {loading ? (
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
        ) : (
          'Add'
        )}
      </button>
      {error && (
        <p className="text-xs text-red-400 mt-1 absolute">{error}</p>
      )}
    </form>
  )
}

// ─── Create tag form ──────────────────────────────────────────────────────────

interface CreateTagFormProps {
  onSubmit: (name: string, color: string) => void
  loading: boolean
  error: string | null
}

function CreateTagForm({ onSubmit, loading, error }: CreateTagFormProps) {
  const [name, setName] = useState('')
  const [color, setColor] = useState(PRESET_COLORS[0])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (name.trim()) {
      onSubmit(name.trim(), color)
      setName('')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 space-y-3">
      {error && (
        <div className="rounded-md bg-red-900/30 border border-red-700 px-3 py-2 text-xs text-red-300">
          {error}
        </div>
      )}
      <div className="flex gap-2">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Tag name"
          className="input-field flex-1"
          disabled={loading}
          maxLength={50}
        />
        <button
          type="submit"
          disabled={loading || !name.trim()}
          className="btn-primary"
        >
          {loading ? (
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
          ) : (
            'Add'
          )}
        </button>
      </div>
      <ColorPicker value={color} onChange={setColor} />
    </form>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Collections() {
  const queryClient = useQueryClient()
  const [folderError, setFolderError] = useState<string | null>(null)
  const [tagError, setTagError] = useState<string | null>(null)

  // Queries
  const {
    data: folders = [],
    isLoading: loadingFolders,
  } = useQuery({ queryKey: ['folders'], queryFn: listFolders })

  const {
    data: tags = [],
    isLoading: loadingTags,
  } = useQuery({ queryKey: ['tags'], queryFn: listTags })

  // Folder mutations
  const createFolderMutation = useMutation({
    mutationFn: (name: string) => createFolder(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['folders'] })
      setFolderError(null)
    },
    onError: (err: unknown) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const detail = (err as any)?.response?.data?.detail
      setFolderError(typeof detail === 'string' ? detail : 'Failed to create folder')
      setTimeout(() => setFolderError(null), 4000)
    },
  })

  const deleteFolderMutation = useMutation({
    mutationFn: (id: number) => deleteFolder(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['folders'] }),
  })

  // Tag mutations
  const createTagMutation = useMutation({
    mutationFn: ({ name, color }: { name: string; color: string }) =>
      createTag(name, color),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tags'] })
      setTagError(null)
    },
    onError: (err: unknown) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const detail = (err as any)?.response?.data?.detail
      setTagError(typeof detail === 'string' ? detail : 'Failed to create tag')
      setTimeout(() => setTagError(null), 4000)
    },
  })

  const deleteTagMutation = useMutation({
    mutationFn: (id: number) => deleteTag(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['tags'] }),
  })

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Header */}
      <div className="flex h-14 items-center border-b border-gray-700 px-6">
        <h1 className="text-sm font-semibold text-gray-200">Collections</h1>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Folders panel */}
          <div className="card">
            <div className="flex items-center gap-2 mb-1">
              <svg className="h-5 w-5 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z" />
              </svg>
              <h2 className="text-sm font-semibold text-gray-200">Folders</h2>
              <span className="rounded-full bg-gray-700 px-2 py-0.5 text-xs text-gray-400">
                {folders.length}
              </span>
            </div>

            <p className="text-xs text-gray-500 mb-3">
              Organize documents into folders for targeted retrieval
            </p>

            {/* Folder list */}
            {loadingFolders ? (
              <div className="flex justify-center py-6">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-gray-600 border-t-blue-500" />
              </div>
            ) : folders.length === 0 ? (
              <div className="rounded-lg border border-gray-700 border-dashed py-6 text-center">
                <p className="text-sm text-gray-600">No folders yet</p>
              </div>
            ) : (
              <div className="rounded-lg border border-gray-700 overflow-hidden divide-y divide-gray-700/50 mb-3">
                {folders.map((folder) => (
                  <FolderItem
                    key={folder.id}
                    folder={folder}
                    onDelete={(id) => deleteFolderMutation.mutate(id)}
                    deleting={deleteFolderMutation.isPending}
                  />
                ))}
              </div>
            )}

            {/* Create form */}
            <div className="relative">
              <CreateFolderForm
                onSubmit={(name) => createFolderMutation.mutate(name)}
                loading={createFolderMutation.isPending}
                error={folderError}
              />
            </div>
          </div>

          {/* Tags panel */}
          <div className="card">
            <div className="flex items-center gap-2 mb-1">
              <svg className="h-5 w-5 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.568 3H5.25A2.25 2.25 0 003 5.25v4.318c0 .597.237 1.17.659 1.591l9.581 9.581c.699.699 1.78.872 2.607.33a18.095 18.095 0 005.223-5.223c.542-.827.369-1.908-.33-2.607L11.16 3.66A2.25 2.25 0 009.568 3z" />
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 6h.008v.008H6V6z" />
              </svg>
              <h2 className="text-sm font-semibold text-gray-200">Tags</h2>
              <span className="rounded-full bg-gray-700 px-2 py-0.5 text-xs text-gray-400">
                {tags.length}
              </span>
            </div>

            <p className="text-xs text-gray-500 mb-3">
              Label documents with colored tags for filtering
            </p>

            {/* Tags list */}
            {loadingTags ? (
              <div className="flex justify-center py-6">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-gray-600 border-t-blue-500" />
              </div>
            ) : tags.length === 0 ? (
              <div className="rounded-lg border border-gray-700 border-dashed py-6 text-center">
                <p className="text-sm text-gray-600">No tags yet</p>
              </div>
            ) : (
              <div className="rounded-lg border border-gray-700 overflow-hidden divide-y divide-gray-700/50 mb-3">
                {tags.map((tag) => (
                  <TagItem
                    key={tag.id}
                    tag={tag}
                    onDelete={(id) => deleteTagMutation.mutate(id)}
                    deleting={deleteTagMutation.isPending}
                  />
                ))}
              </div>
            )}

            {/* Create form */}
            <CreateTagForm
              onSubmit={(name, color) => createTagMutation.mutate({ name, color })}
              loading={createTagMutation.isPending}
              error={tagError}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
