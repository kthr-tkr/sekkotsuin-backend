<script setup lang="ts">
definePageMeta({ layout: 'portal', public: true })

const route = useRoute()
const { slug, setToken, fetchMe } = usePortal()
const token = String(route.query.token ?? '')
const password = ref('')
const confirmPassword = ref('')
const error = ref<string | null>(null)
const loading = ref(false)

const minPw = (v: string) => v.length >= 8 || '8文字以上で入力してください'
const same = (v: string) => v === password.value || 'パスワードが一致しません'

async function submit(e: Promise<{ valid: boolean }>) {
  if (!(await e).valid) return
  loading.value = true
  error.value = null
  const { data, error: err } = await useApi().POST('/api/portal/{slug}/password-reset/confirm', {
    params: { path: { slug: slug.value } },
    body: { token, password: password.value },
  })
  loading.value = false
  if (err || !data) return (error.value = errorMessage(err))
  setToken(data.access_token)
  await fetchMe()
  await navigateTo(`/c/${slug.value}/mypage`)
}
</script>

<template>
  <v-card class="pa-2">
    <v-card-title>新しいパスワードの設定</v-card-title>
    <v-card-text>
      <v-alert v-if="!token" type="warning" variant="tonal" text="リンクが正しくありません。メールのリンクから開いてください。" />
      <v-form v-else @submit.prevent="submit">
        <v-text-field v-model="password" type="password" label="新しいパスワード（8文字以上）" :rules="[minPw]" autocomplete="new-password" />
        <v-text-field v-model="confirmPassword" type="password" label="新しいパスワード（確認）" :rules="[same]" autocomplete="new-password" />
        <v-alert v-if="error" type="error" variant="tonal" class="mb-4" :text="error" />
        <v-btn type="submit" color="primary" block size="large" :loading="loading">設定してログイン</v-btn>
      </v-form>
      <v-btn v-if="error || !token" variant="text" block class="mt-3" :to="`/c/${slug}/forgot`">もう一度手続きする</v-btn>
    </v-card-text>
  </v-card>
</template>
