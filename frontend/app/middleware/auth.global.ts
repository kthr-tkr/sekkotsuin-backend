// 認証不要のページは definePageMeta({ public: true }) を指定する
export default defineNuxtRouteMiddleware(async (to) => {
  // 患者向けポータル（/c/...）と公開ページはスタッフのログイン不要
  if (to.meta.public || to.path.startsWith('/c/')) return
  const { token, user, fetchMe } = useAuth()
  if (!token.value) return navigateTo('/login')
  if (!user.value && !(await fetchMe())) return navigateTo('/login')
})
