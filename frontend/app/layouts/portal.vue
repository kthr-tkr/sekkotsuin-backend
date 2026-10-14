<script setup lang="ts">
const { slug, me, logout } = usePortal()
const { data } = await usePortalClinic(slug.value)
const clinic = computed(() => data.value?.clinic)

async function doLogout() {
  logout()
  await navigateTo(`/c/${slug.value}`)
}
</script>

<template>
  <v-app-bar flat border="b" density="comfortable" color="surface">
    <v-app-bar-title>
      <NuxtLink :to="`/c/${slug}`" class="text-decoration-none text-high-emphasis">
        {{ clinic?.name ?? '' }}
      </NuxtLink>
    </v-app-bar-title>
    <template v-if="clinic">
      <v-btn v-if="me" :to="`/c/${slug}/mypage`" prepend-icon="mdi-account-circle-outline" variant="text">
        マイページ
      </v-btn>
      <v-btn v-if="me" icon="mdi-logout" variant="text" aria-label="ログアウト" @click="doLogout" />
      <v-btn v-else :to="`/c/${slug}/login`" variant="text">ログイン</v-btn>
    </template>
  </v-app-bar>
  <v-main class="bg-background">
    <v-container class="py-6" style="max-width: 760px">
      <v-alert v-if="data?.error" type="warning" variant="tonal" :text="data.error" />
      <slot v-else />
    </v-container>
  </v-main>
</template>
