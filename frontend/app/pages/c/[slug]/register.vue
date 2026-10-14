<script setup lang="ts">
definePageMeta({ layout: 'portal', public: true })

const { slug, setToken, fetchMe } = usePortal()
const api = useApi()
const tab = ref<'new' | 'link'>('new')
const error = ref<string | null>(null)
const loading = ref(false)

const form = reactive({
  last_name: '',
  first_name: '',
  last_name_kana: '',
  first_name_kana: '',
  birth_date: '',
  phone: '',
  email: '',
  password: '',
})
const required = (v: string) => !!v || '入力してください'
const kana = (v: string) => /^[ァ-ヶーぁ-ゖ\s　]+$/.test(v) || 'カタカナで入力してください'
const minPw = (v: string) => v.length >= 8 || '8文字以上で入力してください'

async function submit(e: Promise<{ valid: boolean }>) {
  if (!(await e).valid) return
  loading.value = true
  error.value = null
  const res =
    tab.value === 'new'
      ? await api.POST('/api/portal/{slug}/register', { params: { path: { slug: slug.value } }, body: form })
      : await api.POST('/api/portal/{slug}/link', {
          params: { path: { slug: slug.value } },
          body: {
            last_name: form.last_name,
            first_name: form.first_name,
            birth_date: form.birth_date,
            phone: form.phone,
            email: form.email,
            password: form.password,
          },
        })
  loading.value = false
  if (res.error || !res.data) {
    error.value = errorMessage(res.error, '登録に失敗しました。')
    return
  }
  setToken(res.data.access_token)
  await fetchMe()
  await navigateTo(`/c/${slug.value}/book`)
}
</script>

<template>
  <v-card>
    <v-tabs v-model="tab" grow color="primary">
      <v-tab value="new">はじめての方</v-tab>
      <v-tab value="link">来院したことがある方</v-tab>
    </v-tabs>
    <v-card-text>
      <p class="mb-4 text-body-medium">
        <template v-if="tab === 'new'">お名前などを登録すると、Web 予約とマイページが使えるようになります。</template>
        <template v-else>院に登録されているお名前・生年月日・電話番号で本人確認をして、ログイン用のアカウントを作ります。</template>
      </p>
      <v-form @submit.prevent="submit">
        <v-row density="compact">
          <v-col cols="6"><v-text-field v-model="form.last_name" label="姓" :rules="[required]" /></v-col>
          <v-col cols="6"><v-text-field v-model="form.first_name" label="名" :rules="[required]" /></v-col>
          <template v-if="tab === 'new'">
            <v-col cols="6"><v-text-field v-model="form.last_name_kana" label="セイ" :rules="[required, kana]" /></v-col>
            <v-col cols="6"><v-text-field v-model="form.first_name_kana" label="メイ" :rules="[required, kana]" /></v-col>
          </template>
          <v-col cols="12" sm="6">
            <v-text-field v-model="form.birth_date" type="date" label="生年月日" :rules="[required]" />
          </v-col>
          <v-col cols="12" sm="6">
            <v-text-field v-model="form.phone" type="tel" label="電話番号" :rules="[required]" autocomplete="tel" />
          </v-col>
          <v-col cols="12">
            <v-text-field v-model="form.email" type="email" label="メールアドレス（ログインに使います）" :rules="[required]" autocomplete="email" />
          </v-col>
          <v-col cols="12">
            <v-text-field
              v-model="form.password"
              type="password"
              label="パスワード（8文字以上）"
              :rules="[required, minPw]"
              autocomplete="new-password"
            />
          </v-col>
        </v-row>
        <v-alert v-if="error" type="error" variant="tonal" class="mb-4" :text="error" />
        <v-btn type="submit" color="primary" size="large" block :loading="loading">
          {{ tab === 'new' ? '登録する' : '本人確認して登録する' }}
        </v-btn>
      </v-form>
    </v-card-text>
  </v-card>
</template>
