<script setup lang="ts">
const tab = ref<'active' | 'paused' | 'completed'>('active')
const page = ref(1)
const perPage = 30

const { data, pending } = await useAsyncData(
  'treatment-plans',
  async () => {
    const { data } = await useApi().GET('/api/treatment-plans', {
      params: { query: { status: tab.value, limit: perPage, offset: (page.value - 1) * perPage } },
    })
    return data ?? { items: [], total: 0 }
  },
  { watch: [tab, page] },
)
watch(tab, () => (page.value = 1))

const headers = [
  { title: '患者', key: 'patient' },
  { title: '計画', key: 'title' },
  { title: '開始日', key: 'start_date' },
  { title: '次回来院日', key: 'next_visit_date' },
  { title: '同意', key: 'consent' },
]
</script>

<template>
  <div>
    <PageHeader title="施術計画" subtitle="患者詳細やカルテから作成できます" />
    <v-card>
      <v-tabs v-model="tab" color="primary">
        <v-tab value="active">進行中</v-tab>
        <v-tab value="paused">中断</v-tab>
        <v-tab value="completed">完了</v-tab>
      </v-tabs>
      <v-data-table-server
        v-model:page="page"
        :headers="headers"
        :items="data?.items ?? []"
        :items-length="data?.total ?? 0"
        :items-per-page="perPage"
        :items-per-page-options="[perPage]"
        :loading="pending"
        hover
        @click:row="(_e: unknown, { item }: { item: { id: number } }) => navigateTo(`/treatment-plans/${item.id}`)"
      >
        <template #item.patient="{ item }">
          {{ item.patient.card_no }} {{ patientName(item.patient) }}
        </template>
        <template #item.title="{ item }">{{ item.title || item.chief_complaint || '（未設定）' }}</template>
        <template #item.next_visit_date="{ item }">{{ item.next_visit_date ?? '-' }}</template>
        <template #item.consent="{ item }">
          <v-chip v-if="item.latest_consent && !item.consent_outdated" size="small" color="success" variant="tonal">
            同意済み
          </v-chip>
          <v-chip v-else size="small" color="warning" variant="tonal">
            {{ item.consent_outdated ? '再同意が必要' : '未同意' }}
          </v-chip>
        </template>
      </v-data-table-server>
    </v-card>
  </div>
</template>
