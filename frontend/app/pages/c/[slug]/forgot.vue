<script setup lang="ts">
definePageMeta({ layout: 'portal', public: true })

const { slug } = usePortal()
const email = ref('')
const done = ref<string | null>(null)
const error = ref<string | null>(null)
const loading = ref(false)

async function submit() {
  loading.value = true
  error.value = null
  const { data, error: err } = await useApi().POST('/api/portal/{slug}/password-reset', {
    params: { path: { slug: slug.value } },
    body: { email: email.value },
  })
  loading.value = false
  if (err) return (error.value = errorMessage(err))
  done.value = (data as { detail?: string } | undefined)?.detail ?? '再設定のご案内を送信しました。'
}
</script>

<template>
  <v-card class="pa-2">
    <v-card-title>パスワードの再設定</v-card-title>
    <v-card-text>
      <v-alert v-if="done" type="success" variant="tonal" class="mb-4">
        {{ done }}<br />メールが届かない場合は、迷惑メールフォルダもご確認ください。
      </v-alert>
      <v-form v-else @submit.prevent="submit">
        <p class="text-body-medium mb-4">登録したメールアドレスに、パスワードを再設定するためのリンクを送ります。</p>
        <v-text-field v-model="email" type="email" label="メールアドレス" autocomplete="email" autofocus />
        <v-alert v-if="error" type="error" variant="tonal" class="mb-4" :text="error" />
        <v-btn type="submit" color="primary" block size="large" :loading="loading" :disabled="!email">送信する</v-btn>
      </v-form>
      <v-btn variant="text" block class="mt-3" :to="`/c/${slug}/login`">ログイン画面に戻る</v-btn>
    </v-card-text>
  </v-card>
</template>
