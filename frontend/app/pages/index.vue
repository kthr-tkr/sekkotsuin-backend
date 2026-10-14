<script setup lang="ts">
const api = useApi()
const { user } = useAuth()

function todayRange() {
  const d = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Tokyo' }).format(new Date())
  const start = `${d}T00:00:00+09:00`
  const end = new Date(new Date(start).getTime() + 86400000).toISOString()
  return { start, end }
}

const { data: today } = await useAsyncData('today-appts', async () => {
  const { data } = await api.GET('/api/appointments', { params: { query: todayRange() } })
  return data ?? []
})
const { data: waiting } = await useAsyncData('waiting-intakes', async () => {
  const { data } = await api.GET('/api/intakes', { params: { query: { submitted: true, limit: 5 } } })
  return data ?? { items: [], total: 0 }
})

const mine = computed(() => (today.value ?? []).filter((a) => a.assigned_staff_id === user.value?.id))
const stats = computed(() => [
  { label: '本日の予約', value: today.value?.length ?? 0, icon: 'mdi-calendar-today' },
  { label: 'あなたの担当', value: mine.value.length, icon: 'mdi-account-heart-outline' },
  {
    label: '問診待ち',
    value: (today.value ?? []).filter((a) => a.status === 'pending').length,
    icon: 'mdi-clipboard-clock-outline',
  },
])
</script>

<template>
  <div>
    <PageHeader title="ダッシュボード" :subtitle="`${user?.full_name} さん、お疲れさまです`" />

    <v-row class="mb-2">
      <v-col v-for="s in stats" :key="s.label" cols="12" sm="4">
        <v-card class="pa-4 d-flex align-center ga-4">
          <v-avatar color="primary" variant="tonal" size="48"><v-icon :icon="s.icon" /></v-avatar>
          <div>
            <div class="text-caption text-medium-emphasis">{{ s.label }}</div>
            <div class="text-h5 font-weight-bold">{{ s.value }}</div>
          </div>
        </v-card>
      </v-col>
    </v-row>

    <v-row>
      <v-col cols="12" md="7">
        <v-card title="本日の予約">
          <template #append>
            <v-btn variant="text" to="/appointments">カレンダー</v-btn>
          </template>
          <v-list>
            <v-list-item v-if="!today?.length" subtitle="本日の予約はありません" />
            <v-list-item
              v-for="a in today"
              :key="a.id"
              :to="a.patient_id ? `/patients/${a.patient_id}` : undefined"
              :title="`${formatTime(a.start_at)}〜${formatTime(a.end_at)}  ${patientName(a.patient)}`"
              :subtitle="[a.menu_name, a.assigned_staff?.full_name].filter(Boolean).join(' / ')"
            >
              <template #append>
                <v-chip size="small" :color="STATUS_COLORS[a.status]" variant="flat">
                  {{ STATUS_LABELS[a.status] }}
                </v-chip>
              </template>
            </v-list-item>
          </v-list>
        </v-card>
      </v-col>
      <v-col cols="12" md="5">
        <v-card title="最近の問診回答">
          <template #append>
            <v-btn variant="text" to="/intakes">すべて</v-btn>
          </template>
          <v-list>
            <v-list-item v-if="!waiting?.items.length" subtitle="回答はまだありません" />
            <v-list-item
              v-for="i in waiting?.items"
              :key="i.id"
              :to="`/intakes/${i.id}`"
              :title="`${patientName(i.patient)}：${i.chief_complaint}`"
              :subtitle="formatDateTime(i.submitted_at)"
            />
          </v-list>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>
