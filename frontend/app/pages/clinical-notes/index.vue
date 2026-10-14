<script setup lang="ts">
const tab = ref<'draft' | 'finalized' | 'all'>('draft')
const page = ref(1)
const perPage = 30

const { data, pending } = await useAsyncData(
  'clinical-notes',
  async () => {
    const { data } = await useApi().GET('/api/clinical-notes', {
      params: {
        query: {
          status: tab.value === 'all' ? undefined : tab.value,
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

const headers = [
  { title: '来院日時', key: 'visited_at' },
  { title: '患者', key: 'patient' },
  { title: '主訴（S）', key: 'subjective' },
  { title: 'PS', key: 'ps' },
  { title: '担当', key: 'practitioner' },
  { title: '状態', key: 'status' },
]
</script>

<template>
  <div>
    <PageHeader title="カルテ" subtitle="予約カレンダーや患者詳細からカルテを作成できます" />
    <v-card>
      <v-tabs v-model="tab" color="primary">
        <v-tab value="draft">下書き</v-tab>
        <v-tab value="finalized">確定済み</v-tab>
        <v-tab value="all">すべて</v-tab>
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
        @click:row="(_e: unknown, { item }: { item: { id: number } }) => navigateTo(`/clinical-notes/${item.id}`)"
      >
        <template #item.visited_at="{ item }">{{ formatDateTime(item.visited_at) }}</template>
        <template #item.patient="{ item }">
          {{ item.patient.card_no }} {{ patientName(item.patient) }}
        </template>
        <template #item.subjective="{ item }">
          <span class="text-truncate d-inline-block" style="max-width: 280px">
            {{ item.subjective || '-' }}
          </span>
        </template>
        <template #item.ps="{ item }">
          {{ item.pain_scale_before ?? '-' }} → {{ item.pain_scale_after ?? '-' }}
        </template>
        <template #item.practitioner="{ item }">{{ item.practitioner?.full_name ?? '-' }}</template>
        <template #item.status="{ item }">
          <v-chip size="small" :color="NOTE_STATUS_COLORS[item.status]" variant="flat">
            {{ NOTE_STATUS_LABELS[item.status] }}
          </v-chip>
        </template>
      </v-data-table-server>
    </v-card>
  </div>
</template>
