<script setup lang="ts">
const q = ref('')
const page = ref(1)
const perPage = 30

const { data, pending } = await useAsyncData(
  'patients',
  async () => {
    const { data } = await useApi().GET('/api/patients', {
      params: {
        query: { q: q.value || undefined, limit: perPage, offset: (page.value - 1) * perPage },
      },
    })
    return data ?? { items: [], total: 0 }
  },
  { watch: [page] },
)

let timer: ReturnType<typeof setTimeout> | undefined
watch(q, () => {
  clearTimeout(timer)
  timer = setTimeout(() => {
    page.value = 1
    refreshNuxtData('patients')
  }, 300)
})

const headers = [
  { title: '診察券番号', key: 'card_no', width: 120 },
  { title: '氏名', key: 'name' },
  { title: 'フリガナ', key: 'kana' },
  { title: '生年月日', key: 'birth_date' },
  { title: '電話番号', key: 'phone' },
]
</script>

<template>
  <div>
    <PageHeader title="患者" :subtitle="`${data?.total ?? 0} 件`">
      <v-btn color="primary" prepend-icon="mdi-account-plus" to="/patients/new">新規登録</v-btn>
    </PageHeader>

    <v-card>
      <v-card-text>
        <v-text-field
          v-model="q"
          prepend-inner-icon="mdi-magnify"
          label="氏名・フリガナ・診察券番号・電話番号で検索"
          clearable
          hide-details
        />
      </v-card-text>
      <v-data-table-server
        v-model:page="page"
        :headers="headers"
        :items="data?.items ?? []"
        :items-length="data?.total ?? 0"
        :items-per-page="perPage"
        :items-per-page-options="[perPage]"
        :loading="pending"
        hover
        @click:row="(_e: unknown, { item }: { item: { id: number } }) => navigateTo(`/patients/${item.id}`)"
      >
        <template #item.name="{ item }">{{ patientName(item) }}</template>
        <template #item.kana="{ item }">
          {{ item.last_name_kana }} {{ item.first_name_kana }}
        </template>
        <template #item.birth_date="{ item }">
          {{ item.birth_date }}（{{ ageOf(item.birth_date) }}歳）
        </template>
      </v-data-table-server>
    </v-card>
  </div>
</template>
