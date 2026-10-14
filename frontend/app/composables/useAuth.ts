import type { Schemas } from './useApi'

export function useAuth() {
  const token = useAccessToken()
  const user = useState<Schemas['UserOut'] | null>('auth-user', () => null)

  async function login(username: string, password: string): Promise<string | null> {
    const { data, error } = await useApi().POST('/api/auth/login', {
      body: { username, password, scope: '' },
      // OAuth2PasswordRequestForm はフォーム形式で受け取る
      bodySerializer: (body) => new URLSearchParams(body as Record<string, string>),
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    })
    if (error || !data) return errorMessage(error, 'ログインに失敗しました。')
    token.value = data.access_token
    await fetchMe()
    return null
  }

  async function fetchMe() {
    if (!token.value) {
      user.value = null
      return null
    }
    const { data } = await useApi().GET('/api/auth/me')
    user.value = data ?? null
    return user.value
  }

  async function logout() {
    token.value = null
    user.value = null
    await navigateTo('/login')
  }

  const isAdmin = computed(() => user.value?.role === 'admin')

  return { token, user, isAdmin, login, logout, fetchMe }
}
