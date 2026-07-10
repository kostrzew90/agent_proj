import { apiClient } from './client'

export interface Folder {
  id: number
  name: string
  parent_id: number | null
  created_at: string
  children: Folder[]
}

export interface Tag {
  id: number
  name: string
  color: string
  created_at: string
  document_count: number
}

// Folders

export async function listFolders(): Promise<Folder[]> {
  const { data } = await apiClient.get<Folder[]>('/folders')
  return data
}

export async function createFolder(name: string, parentId?: number): Promise<Folder> {
  const { data } = await apiClient.post<Folder>('/folders', {
    name,
    parent_id: parentId ?? null,
  })
  return data
}

export async function updateFolder(
  id: number,
  name?: string,
  parentId?: number,
): Promise<Folder> {
  const { data } = await apiClient.put<Folder>(`/folders/${id}`, {
    name,
    parent_id: parentId,
  })
  return data
}

export async function deleteFolder(id: number): Promise<void> {
  await apiClient.delete(`/folders/${id}`)
}

// Tags

export async function listTags(): Promise<Tag[]> {
  const { data } = await apiClient.get<Tag[]>('/tags')
  return data
}

export async function createTag(name: string, color: string): Promise<Tag> {
  const { data } = await apiClient.post<Tag>('/tags', { name, color })
  return data
}

export async function deleteTag(id: number): Promise<void> {
  await apiClient.delete(`/tags/${id}`)
}
