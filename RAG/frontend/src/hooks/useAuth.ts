import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  ReactNode,
  createElement,
} from 'react'
import { login as apiLogin, getCurrentUser, User } from '../api/auth'
import { setToken, clearToken, getToken } from '../api/client'

interface AuthContextType {
  user: User | null
  isLoading: boolean
  error: string | null
  login: (username: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextType | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // On mount: try to restore session from stored token
  useEffect(() => {
    const token = getToken()
    if (!token) {
      setIsLoading(false)
      return
    }

    getCurrentUser()
      .then((u) => {
        setUser(u)
      })
      .catch(() => {
        clearToken()
      })
      .finally(() => {
        setIsLoading(false)
      })
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    setError(null)
    setIsLoading(true)
    try {
      const response = await apiLogin(username, password)
      setToken(response.access_token)
      setUser({
        id: response.user_id,
        username: response.username,
        display_name: response.display_name,
        is_admin: response.is_admin,
      })
    } catch (err: unknown) {
      const message =
        err instanceof Error ? err.message : 'Login failed. Check your credentials.'
      setError(message)
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [])

  const logout = useCallback(() => {
    clearToken()
    setUser(null)
    window.location.href = '/login'
  }, [])

  return createElement(
    AuthContext.Provider,
    { value: { user, isLoading, error, login, logout } },
    children,
  )
}

export function useAuth(): AuthContextType {
  const ctx = useContext(AuthContext)
  if (!ctx) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return ctx
}
