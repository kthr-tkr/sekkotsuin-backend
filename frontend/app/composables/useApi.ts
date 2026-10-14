import createClient, { type Middleware } from 'openapi-fetch'
import type { components, paths } from '~/types/api'

export type Schemas = components['schemas']

const TOKEN_KEY = 'access_token'
const TOKEN_MAX_AGE = 60 * 60 * 12 // backend の ACCESS_TOKEN_EXPIRE_MINUTES に合わせる

function readTokenCookie(): string | null {
  const m = document.cookie.match(new RegExp(`(?:^|; )${TOKEN_KEY}=([^;]*)`))
  return m ? decodeURIComponent(m[1]!) : null
}

// useCookie は書き込みが非同期のため、ログイン直後のリクエストでも確実に読めるよう共有 ref で保持する
const accessToken = ref<string | null>(null)
let tokenLoaded = false

export function useAccessToken() {
  if (!tokenLoaded) {
    accessToken.value = readTokenCookie()
    tokenLoaded = true
  }
  return computed<string | null>({
    get: () => accessToken.value,
    set: (v) => {
      accessToken.value = v
      document.cookie = v
        ? `${TOKEN_KEY}=${encodeURIComponent(v)}; path=/; max-age=${TOKEN_MAX_AGE}; samesite=strict`
        : `${TOKEN_KEY}=; path=/; max-age=0; samesite=strict`
    },
  })
}

let client: ReturnType<typeof createClient<paths>> | null = null

/** 型付き API クライアント（openapi-fetch）。認証トークンを自動付与し、401 でログイン画面へ。 */
export function useApi() {
  if (client) return client
  const config = useRuntimeConfig()
  client = createClient<paths>({ baseUrl: config.public.apiBase })

  const auth: Middleware = {
    onRequest({ request }) {
      const token = useAccessToken().value
      if (token) request.headers.set('Authorization', `Bearer ${token}`)
      return request
    },
    async onResponse({ response, request }) {
      const isPublic = new URL(request.url).pathname.startsWith('/api/public/')
      if (response.status === 401 && !isPublic) {
        useAccessToken().value = null
        await navigateTo('/login')
      }
      return response
    },
  }
  client.use(auth)
  return client
}

/** FastAPI のエラーレスポンス（detail）を表示用の文字列に変換する。 */
export function errorMessage(error: unknown, fallback = 'エラーが発生しました。'): string {
  const detail = (error as { detail?: unknown } | undefined)?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d: { msg?: string }) => d.msg?.replace(/^Value error, /, ''))
      .filter(Boolean)
      .join('\n') || fallback
  }
  return fallback
}
