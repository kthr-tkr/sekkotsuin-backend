<script setup lang="ts">
const { isAdmin } = useAuth()
if (!isAdmin.value) await navigateTo('/')

const month = ref(currentMonth())
const { data: k } = await useAsyncData(
  'kpi',
  async () => {
    const { data } = await useApi().GET('/api/kpi', { params: { query: { month: month.value } } })
    return data ?? null
  },
  { watch: [month] },
)

const diff = computed(() => {
  if (!k.value || !k.value.sales_total_prev_month) return null
  return (k.value.sales_total - k.value.sales_total_prev_month) / k.value.sales_total_prev_month
})
const tiles = computed(() => {
  const v = k.value
  if (!v) return []
  return [
    { label: '売上（支払い済み）', value: yen(v.sales_total), note: diff.value === null ? '前月の売上なし' : `前月比 ${diff.value >= 0 ? '+' : ''}${Math.round(diff.value * 100)}%` },
    { label: '来院数（完了した予約）', value: `${v.visits}件`, note: `予約 ${v.appointments}件` },
    { label: '客単価', value: yen(v.average_spend), note: `会計 ${v.paid_count}件` },
    { label: '新規患者', value: `${v.new_patients}人`, note: '患者登録の件数' },
    { label: 'キャンセル率', value: `${Math.round(v.cancel_rate * 1000) / 10}%`, note: `${v.cancellations}件（無断を含む）` },
    { label: '未会計', value: yen(v.unpaid_amount), note: `${v.unpaid_count}件` },
  ]
})
const bars = computed(() =>
  (k.value?.daily ?? []).map((d) => ({
    label: String(Number(d.date.slice(8))),
    value: d.sales,
    tooltip: `${d.date}（${weekdayJa(d.date)}）来院 ${d.visits}件`,
  })),
)
const maxSource = computed(() => Math.max(1, ...(k.value?.booking_sources ?? []).map((s) => s.count)))
</script>

<template>
  <div v-if="k">
    <PageHeader title="KPI" subtitle="売上・来院・予約の月次の状況">
      <MonthPicker v-model="month" />
    </PageHeader>

    <v-row class="mb-2">
      <v-col v-for="t in tiles" :key="t.label" cols="12" sm="6" md="4">
        <v-card class="pa-4">
          <div class="text-body-small text-medium-emphasis">{{ t.label }}</div>
          <div class="text-headline-small font-weight-bold">{{ t.value }}</div>
          <div class="text-body-small text-medium-emphasis">{{ t.note }}</div>
        </v-card>
      </v-col>
    </v-row>

    <v-card class="mb-4" title="日別の売上">
      <v-card-text>
        <ColumnChart :bars="bars" :format="yen" label="日別の売上（支払い済み）" />
      </v-card-text>
    </v-card>

    <v-row>
      <v-col cols="12" md="5">
        <v-card title="予約経路" subtitle="キャンセルを除く予約の件数">
          <v-card-text>
            <p v-if="!k.booking_sources.length" class="text-medium-emphasis">予約はありません</p>
            <div v-for="s in k.booking_sources" :key="s.source" class="source-row">
              <span class="source-label">{{ BOOKING_SOURCE_LABELS[s.source] }}</span>
              <span class="source-bar-wrap">
                <span class="source-bar" :style="{ width: `${(s.count / maxSource) * 100}%` }" />
              </span>
              <span class="source-value">{{ s.count }}</span>
            </div>
          </v-card-text>
        </v-card>
      </v-col>
      <v-col cols="12" md="7">
        <v-card title="担当者別">
          <v-table density="comfortable">
            <thead>
              <tr>
                <th>担当</th>
                <th class="text-right">売上</th>
                <th class="text-right">来院</th>
                <th class="text-right">カルテ</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in k.by_staff" :key="s.staff_id">
                <td>{{ s.name }}</td>
                <td class="text-right">{{ yen(s.sales) }}</td>
                <td class="text-right">{{ s.visits }}</td>
                <td class="text-right">{{ s.notes }}</td>
              </tr>
            </tbody>
          </v-table>
        </v-card>
      </v-col>
    </v-row>
  </div>
</template>

<style scoped>
.source-row {
  display: grid;
  grid-template-columns: 96px 1fr 40px;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}
.source-bar-wrap {
  height: 16px;
}
.source-bar {
  display: block;
  height: 16px;
  min-width: 2px;
  background: #2a78d6;
  border-radius: 0 4px 4px 0;
}
.source-value {
  text-align: right;
  font-weight: 600;
}
</style>
