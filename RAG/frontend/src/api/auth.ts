import { apiClient } from './client'

export interface LoginResponse {
  access_token: string
  token_type: string
  user_id: number
  username: string
  display_name: string | null
  is_admin: boolean
}

export interface User {
  id: number
  username: string
  display_name: string | null
  is_admin: boolean
}

export async function login(
  username: string,
  password: string,
): Promise<LoginResponse> {
  const { data } = await apiClient.post<LoginResponse>('/auth/login', {
    username,
    password,
  })
  return data
}

export async function getCurrentUser(): Promise<User> {
  const { data } = await apiClient.get<User>('/auth/me')
  return data
}
