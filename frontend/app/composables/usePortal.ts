import type { Schemas } from './useApi'

/** 患者向けポータル（/c/[slug]）の院情報とログイン状態 */
export function usePortal() {
  const route = useRoute()
  const slug = computed(() => String(route.params.slug))
  const token = usePatientToken()
  const me = useState<Schemas['MeOut'] | null>('portal-me', () => null)

  async function fetchMe() {
    if (!token.value) return (me.value = null)
    const { data } = await useApi().GET('/api/me')
    // 別の院のアカウントでログインしている場合はこの院では使わない
    me.value = data && data.clinic_slug === slug.value ? data : null
    return me.value
  }

  function setToken(t: string) {
    token.value = t
  }

  function logout() {
    token.value = null
    me.value = null
  }

  return { slug, token, me, fetchMe, setToken, logout }
}

export async function usePortalClinic(slug: string) {
  return useAsyncData(`portal-clinic-${slug}`, async () => {
    const { data, error } = await useApi().GET('/api/portal/{slug}', {
      params: { path: { slug } },
    })
    if (error) return { error: errorMessage(error, 'この院のページは見つかりませんでした。') }
    return { clinic: data! }
  })
}
