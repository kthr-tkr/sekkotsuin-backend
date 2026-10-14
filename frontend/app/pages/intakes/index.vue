<script setup lang="ts">
const tab = ref<'submitted' | 'waiting'>('submitted')
const page = ref(1)
const perPage = 30

const { data, pending } = await useAsyncData(
  'intakes',
  async () => {
    const { data } = await useApi().GET('/api/intakes', {
      params: {
        query: {
          submitted: tab.value === 'submitted',
          limit: perPage,
          offset: (page.value - 1) * perPage,
        },
      },
    })
    return data ?? { items: [], total: 0 }
  },
  { watch: [tab, page] },
)
watch(tab, () => (page.value = 1))

const headers = computed(() => [
  { title: '患者', key: 'patient' },
  ...(tab.value === 'submitted'
    ? [
        { title: '主訴', key: 'chief_complaint' },
        { title: '症状', key: 'symptom_type' },
        { title: '回答日時', key: 'submitted_at' },
      ]
    : [
        { title: '発行日時', key: 'created_at' },
        { title: 'URL有効期限', key: 'token_expires_at' },
      ]),
])
</script>

<template>
  <div>
    <PageHeader title="問診" />
    <v-card>
      <v-tabs v-model="tab" color="primary">
        <v-tab value="submitted">回答済み</v-tab>
        <v-tab value="waiting">未回答</v-tab>
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
        @click:row="(_e: unknown, { item }: { item: { id: number; patient_id: number } }) =>
          navigateTo(tab === 'submitted' ? `/intakes/${item.id}` : `/patients/${item.patient_id}`)"
      >
        <template #item.patient="{ item }">
          {{ item.patient.card_no }} {{ patientName(item.patient) }}
        </template>
        <template #item.symptom_type="{ item }">{{ SYMPTOM_LABELS[item.symptom_type] }}</template>
        <template #item.submitted_at="{ item }">{{ formatDateTime(item.submitted_at) }}</template>
        <template #item.created_at="{ item }">{{ formatDateTime(item.created_at) }}</template>
        <template #item.token_expires_at="{ item }">{{ formatDateTime(item.token_expires_at) }}</template>
      </v-data-table-server>
    </v-card>
  </div>
</template>
