<script setup lang="ts">
definePageMeta({ layout: 'portal', public: true })

const route = useRoute()
const { slug, setToken, fetchMe } = usePortal()
const loginId = ref('')
const password = ref('')
const error = ref<string | null>(null)
const loading = ref(false)

const next = computed(() => {
  const n = String(route.query.next ?? '')
  // 同じ院のポータル内だけに戻す（オープンリダイレクト対策）
  return n.startsWith(`/c/${slug.value}/`) ? n : `/c/${slug.value}/mypage`
})

async function submit() {
  loading.value = true
  error.value = null
  const { data, error: err } = await useApi().POST('/api/portal/{slug}/login', {
    params: { path: { slug: slug.value } },
    body: { login_id: loginId.value, password: password.value },
  })
  loading.value = false
  if (err || !data) return (error.value = errorMessage(err, 'ログインに失敗しました。'))
  setToken(data.access_token)
  await fetchMe()
  await navigateTo(next.value)
}
</script>

<template>
  <v-card class="pa-2">
    <v-card-title>ログイン</v-card-title>
    <v-card-text>
      <v-form @submit.prevent="submit">
        <v-text-field
          v-model="loginId"
          label="メールアドレス または 診察券番号"
          autocomplete="username"
          autofocus
        />
        <v-text-field v-model="password" label="パスワード" type="password" autocomplete="current-password" />
        <v-alert v-if="error" type="error" variant="tonal" class="mb-4" :text="error" />
        <v-btn type="submit" color="primary" block size="large" :loading="loading">ログイン</v-btn>
      </v-form>
      <v-divider class="my-4" />
      <v-btn variant="text" block :to="`/c/${slug}/register`">はじめての方・アカウントをお持ちでない方</v-btn>
    </v-card-text>
  </v-card>
</template>
