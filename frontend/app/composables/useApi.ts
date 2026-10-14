import createClient, { type Middleware } from 'openapi-fetch'
import type { components, paths } from '~/types/api'

export type Schemas = components['schemas']

/**
 * Cookie に保存するトークン。useCookie は書き込みが非同期のため、
 * ログイン直後のリクエストでも確実に読めるよう共有 ref で保持する。
 */
function makeTokenStore(key: string, maxAgeSec: number) {
  const token = ref<string | null>(null)
  let loaded = false
  return () => {
    if (!loaded) {
      const m = document.cookie.match(new RegExp(`(?:^|; )${key}=([^;]*)`))
      token.value = m ? decodeURIComponent(m[1]!) : null
      loaded = true
    }
    return computed<string | null>({
      get: () => token.value,
      set: (v) => {
        token.value = v
        document.cookie = v
          ? `${key}=${encodeURIComponent(v)}; path=/; max-age=${maxAgeSec}; samesite=strict`
          : `${key}=; path=/; max-age=0; samesite=strict`
      },
    })
  }
}

/** スタッフのトークン（backend の ACCESS_TOKEN_EXPIRE_MINUTES に合わせる） */
export const useAccessToken = makeTokenStore('access_token', 60 * 60 * 12)
/** 患者向けポータルのトークン（スタッフのトークンとは別に保持する） */
export const usePatientToken = makeTokenStore('patient_token', 60 * 60 * 24 * 7)

let client: ReturnType<typeof createClient<paths>> | null = null

/** 型付き API クライアント（openapi-fetch）。認証トークンを自動付与し、401 でログイン画面へ。 */
export function useApi() {
  if (client) return client
  const config = useRuntimeConfig()
  client = createClient<paths>({ baseUrl: config.public.apiBase })

  const auth: Middleware = {
    // パスでトークンを使い分ける: /api/me は患者、/api/portal と /api/public は認証なし
    onRequest({ request }) {
      const path = new URL(request.url).pathname
      if (path.startsWith('/api/portal/') || path.startsWith('/api/public/')) return request
      const token = path.startsWith('/api/me') ? usePatientToken().value : useAccessToken().value
      if (token) request.headers.set('Authorization', `Bearer ${token}`)
      return request
    },
    async onResponse({ response, request }) {
      if (response.status !== 401) return response
      const path = new URL(request.url).pathname
      if (path.startsWith('/api/me')) {
        usePatientToken().value = null
        const slug = window.location.pathname.match(/^\/c\/([^/]+)/)?.[1]
        if (slug) await navigateTo(`/c/${slug}/login?next=${encodeURIComponent(window.location.pathname)}`)
      } else if (!path.startsWith('/api/portal/') && !path.startsWith('/api/public/')) {
        useAccessToken().value = null
        await navigateTo('/login')
      }
      return response
    },
  }
  client.use(auth)
  return client
}

/** API が返す署名付きファイルURL（/api/files/...）を絶対URLにする */
export function fileUrl(path: string | null | undefined): string | undefined {
  return path ? `${useRuntimeConfig().public.apiBase}${path}` : undefined
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
