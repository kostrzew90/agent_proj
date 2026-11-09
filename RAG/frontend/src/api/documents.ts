import { apiClient } from './client'

export interface DocumentItem {
  id: number
  filename: string
  file_type: string
  file_size: number | null
  page_count: number | null
  status: 'pending' | 'processing' | 'ready' | 'error'
  source_type: string
  source_url: string | null
  created_at: string
  processed_at: string | null
  error_message: string | null
  folder_ids: number[]
  tag_ids: number[]
  task_progress: number | null
  task_status: string | null
  task_type: string | null
}

export interface DocumentListResponse {
  documents: DocumentItem[]
  total: number
}

export interface TaskStatus {
  task_id: number
  document_id: number
  task_type: string
  status: string
  progress: number
  error_message: string | null
}

export interface CrawlResponse {
  document_id: number
  task_id: number
  url: string
  status: string
}

export async function uploadDocument(
  file: File,
  folderId?: number,
  tagIds?: number[],
): Promise<DocumentItem> {
  const formData = new FormData()
  formData.append('file', file)

  const params = new URLSearchParams()
  if (folderId !== undefined) params.set('folder_id', String(folderId))
  if (tagIds && tagIds.length > 0) params.set('tag_ids', tagIds.join(','))

  const queryString = params.toString()
  const url = `/documents/upload${queryString ? `?${queryString}` : ''}`

  const { data } = await apiClient.post<DocumentItem>(url, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function listDocuments(params?: {
  folder_id?: number
  tag_id?: number
  status?: string
  file_type?: string
  limit?: number
  offset?: number
}): Promise<DocumentListResponse> {
  const { data } = await apiClient.get<DocumentListResponse>('/documents', {
    params,
  })
  return data
}

export async function getDocument(id: number): Promise<DocumentItem> {
  const { data } = await apiClient.get<DocumentItem>(`/documents/${id}`)
  return data
}

export async function deleteDocument(id: number): Promise<void> {
  await apiClient.delete(`/documents/${id}`)
}

export async function renameDocument(id: number, filename: string): Promise<DocumentItem> {
  const { data } = await apiClient.patch<DocumentItem>(`/documents/${id}`, { filename })
  return data
}

export async function crawlUrl(
  url: string,
  depth: number,
  folderId?: number,
  tagIds?: number[],
): Promise<CrawlResponse> {
  const { data } = await apiClient.post<CrawlResponse>('/documents/crawl', {
    url,
    depth,
    folder_id: folderId ?? null,
    tag_ids: tagIds ?? [],
  })
  return data
}

export async function ingestYoutube(
  url: string,
  languages?: string[],
): Promise<CrawlResponse> {
  const { data } = await apiClient.post<CrawlResponse>('/documents/youtube', {
    url,
    languages: languages ?? ['pl', 'en'],
  })
  return data
}

export async function getTaskStatus(taskId: number): Promise<TaskStatus> {
  const { data } = await apiClient.get<TaskStatus>(`/documents/tasks/${taskId}`)
  return data
}
