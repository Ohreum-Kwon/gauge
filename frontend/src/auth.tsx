import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { api, ApiError, tokenStore } from './api'
import type { User } from './types'

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [token, setToken] = useState(tokenStore.get)

  const logout = useCallback(() => {
    tokenStore.clear()
    setToken(null)
    queryClient.clear()
  }, [queryClient])

  const me = useQuery({
    queryKey: ['me', token],
    queryFn: async () => {
      try {
        return await api.me()
      } catch (error) {
        // A stale or expired token: drop it and show the login page.
        if (error instanceof ApiError && error.status === 401) logout()
        throw error
      }
    },
    enabled: token !== null,
    retry: false,
  })

  const login = useCallback(async (email: string, password: string) => {
    const { access_token } = await api.login(email, password)
    tokenStore.set(access_token)
    setToken(access_token)
  }, [])

  const value = useMemo(
    () => ({
      user: token ? (me.data ?? null) : null,
      loading: token !== null && me.isPending,
      login,
      logout,
    }),
    [token, me.data, me.isPending, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

// eslint-disable-next-line react/only-export-components
export function useAuth(): AuthState {
  const auth = useContext(AuthContext)
  if (!auth) throw new Error('useAuth must be used inside <AuthProvider>')
  return auth
}
