// 認証不要のページは definePageMeta({ public: true }) を指定する
export default defineNuxtRouteMiddleware(async (to) => {
  if (to.meta.public) return
  const { token, user, fetchMe } = useAuth()
  if (!token.value) return navigateTo('/login')
  if (!user.value && !(await fetchMe())) return navigateTo('/login')
})
