<script setup lang="ts">
const { user, isAdmin, logout } = useAuth()
const drawer = ref(true)

const { data: clinic } = await useAsyncData('clinic', async () => {
  const { data } = await useApi().GET('/api/clinic')
  return data ?? null
})

const items = computed(() => [
  { title: 'ダッシュボード', icon: 'mdi-view-dashboard-outline', to: '/' },
  { title: '予約カレンダー', icon: 'mdi-calendar-month-outline', to: '/appointments' },
  { title: '患者', icon: 'mdi-account-multiple-outline', to: '/patients' },
  { title: 'カルテ', icon: 'mdi-file-document-edit-outline', to: '/clinical-notes' },
  { title: '施術計画', icon: 'mdi-flag-checkered', to: '/treatment-plans' },
  { title: '問診', icon: 'mdi-clipboard-text-outline', to: '/intakes' },
  { title: '売上', icon: 'mdi-cash-register', to: '/sales' },
  { title: 'シフト・休暇', icon: 'mdi-calendar-account-outline', to: '/schedule' },
  ...(isAdmin.value
    ? [
        { title: 'KPI', icon: 'mdi-chart-box-outline', to: '/kpi' },
        { title: '院の設定', icon: 'mdi-cog-outline', to: '/settings' },
      ]
    : []),
])
</script>

<template>
  <v-navigation-drawer v-model="drawer" width="232" class="d-print-none">
    <v-list-item class="py-4" title="接骨院システム" :subtitle="user?.full_name" />
    <v-divider />
    <v-list nav density="comfortable">
      <v-list-item
        v-for="item in items"
        :key="item.to"
        :to="item.to"
        :prepend-icon="item.icon"
        :title="item.title"
        :exact="item.to === '/'"
        color="primary"
      />
    </v-list>
    <template #append>
      <v-list nav density="comfortable">
        <v-list-item prepend-icon="mdi-logout" title="ログアウト" @click="logout" />
      </v-list>
    </template>
  </v-navigation-drawer>

  <v-app-bar flat border="b" density="comfortable" class="d-print-none">
    <v-app-bar-nav-icon @click="drawer = !drawer" />
    <v-app-bar-title>{{ clinic?.name }}</v-app-bar-title>
    <v-chip v-if="user" class="mr-4" size="small" variant="tonal">
      {{ ROLE_LABELS[user.role] }}
    </v-chip>
  </v-app-bar>

  <v-main>
    <v-container fluid class="pa-4 pa-md-6">
      <slot />
    </v-container>
  </v-main>
</template>
