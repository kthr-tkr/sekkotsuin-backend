<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

const month = ref(currentMonth())
const tab = ref<'all' | 'unpaid' | 'paid' | 'canceled'>('all')
const page = ref(1)
const perPage = 50

const range = computed(() => {
  const days = daysInMonth(month.value)
  return { start: days[0]!, end: days[days.length - 1]! }
})

const { data, pending, refresh } = await useAsyncData(
  'sales',
  async () => {
    const { data } = await useApi().GET('/api/sales', {
      params: {
        query: {
          ...range.value,
          status: tab.value === 'all' ? undefined : tab.value,
          limit: perPage,
          offset: (page.value - 1) * perPage,
        },
      },
    })
    return data ?? { items: [], total: 0, paid_amount: 0, unpaid_amount: 0 }
  },
  { watch: [month, tab, page] },
)
watch([month, tab], () => (page.value = 1))

const dialog = ref(false)
const editing = ref<Schemas['SalesOut'] | null>(null)
function openDialog(r: Schemas['SalesOut'] | null) {
  editing.value = r
  dialog.value = true
}

const headers = [
  { title: '施術日', key: 'treatment_date' },
  { title: '患者', key: 'patient' },
  { title: '明細', key: 'description' },
  { title: '担当', key: 'staff' },
  { title: '支払方法', key: 'payment_method' },
  { title: '金額', key: 'amount', align: 'end' as const },
  { title: '状態', key: 'status' },
]
</script>

<template>
  <div>
    <PageHeader title="売上">
      <MonthPicker v-model="month" />
      <v-btn color="primary" prepend-icon="mdi-plus" @click="openDialog(null)">会計を登録</v-btn>
    </PageHeader>

    <v-row class="mb-2">
      <v-col cols="12" sm="6">
        <v-card class="pa-4">
          <div class="text-body-small text-medium-emphasis">支払い済み（{{ month }}）</div>
          <div class="text-headline-small font-weight-bold">{{ yen(data?.paid_amount ?? 0) }}</div>
        </v-card>
      </v-col>
      <v-col cols="12" sm="6">
        <v-card class="pa-4">
          <div class="text-body-small text-medium-emphasis">未会計</div>
          <div class="text-headline-small font-weight-bold">{{ yen(data?.unpaid_amount ?? 0) }}</div>
        </v-card>
      </v-col>
    </v-row>

    <v-card>
      <v-tabs v-model="tab" color="primary">
        <v-tab value="all">すべて</v-tab>
        <v-tab value="unpaid">未会計</v-tab>
        <v-tab value="paid">支払い済み</v-tab>
        <v-tab value="canceled">取消</v-tab>
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
        @click:row="(_e: unknown, { item }: { item: Schemas['SalesOut'] }) => openDialog(item)"
      >
        <template #item.patient="{ item }">{{ item.patient.card_no }} {{ patientName(item.patient) }}</template>
        <template #item.staff="{ item }">{{ item.staff?.full_name ?? '-' }}</template>
        <template #item.payment_method="{ item }">{{ PAYMENT_LABELS[item.payment_method] }}</template>
        <template #item.amount="{ item }">{{ yen(item.amount) }}</template>
        <template #item.status="{ item }">
          <v-chip size="small" :color="SALES_STATUS_COLORS[item.status]" variant="flat">
            {{ SALES_STATUS_LABELS[item.status] }}
          </v-chip>
        </template>
      </v-data-table-server>
    </v-card>

    <SalesDialog v-model="dialog" :record="editing" @saved="refresh" />
  </div>
</template>
