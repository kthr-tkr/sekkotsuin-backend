<script setup lang="ts">
definePageMeta({ layout: 'public', public: true })

const { login } = useAuth()
const username = ref('')
const password = ref('')
const error = ref<string | null>(null)
const loading = ref(false)

async function submit() {
  loading.value = true
  error.value = await login(username.value, password.value)
  loading.value = false
  if (!error.value) await navigateTo('/')
}
</script>

<template>
  <v-card class="mx-auto mt-16 pa-4" max-width="420">
    <v-card-title class="text-h6">スタッフログイン</v-card-title>
    <v-card-text>
      <v-form @submit.prevent="submit">
        <v-text-field v-model="username" label="ユーザー名" autocomplete="username" autofocus />
        <v-text-field
          v-model="password"
          label="パスワード"
          type="password"
          autocomplete="current-password"
        />
        <v-alert v-if="error" type="error" variant="tonal" class="mb-4" :text="error" />
        <v-btn type="submit" color="primary" block size="large" :loading="loading">
          ログイン
        </v-btn>
      </v-form>
    </v-card-text>
  </v-card>
</template>
