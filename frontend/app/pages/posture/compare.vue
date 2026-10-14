<script setup lang="ts">
/** 2つの姿勢評価を方向ごとに並べて比較する（/posture/compare?before=1&after=2） */
const route = useRoute()
const api = useApi()
const beforeId = Number(route.query.before)
const afterId = Number(route.query.after)
const grid = ref(true)

async function load(id: number) {
  const { data } = await api.GET('/api/posture-assessments/{assessment_id}', {
    params: { path: { assessment_id: id } },
  })
  return data ?? null
}
const { data: pair } = await useAsyncData(`posture-compare-${beforeId}-${afterId}`, async () => {
  const [before, after] = await Promise.all([load(beforeId), load(afterId)])
  return before && after ? { before, after } : null
})

const imageOf = (side: 'before' | 'after', view: string) =>
  pair.value?.[side].images.find((i) => i.view === view)
const views = computed(() =>
  POSTURE_VIEWS.filter((v) => imageOf('before', v.value) || imageOf('after', v.value)),
)
const regionOf = (side: 'before' | 'after', key: string) =>
  (pair.value?.[side].findings.regions as Record<string, string> | undefined)?.[key] ?? ''
const regions = computed(() =>
  POSTURE_REGIONS.filter((r) => regionOf('before', r.key) || regionOf('after', r.key)),
)
</script>

<template>
  <div v-if="pair">
    <PageHeader
      :title="`姿勢の比較: ${patientName(pair.before.patient)}`"
      :subtitle="`Before ${formatDate(pair.before.assessed_at)} → After ${formatDate(pair.after.assessed_at)}`"
    >
      <v-switch v-model="grid" label="グリッド線" color="primary" hide-details density="compact" class="flex-grow-0" />
      <v-btn variant="tonal" :to="`/patients/${pair.before.patient_id}`">患者詳細</v-btn>
    </PageHeader>

    <v-card v-for="v in views" :key="v.value" class="mb-4" :title="v.title">
      <v-card-text>
        <v-row>
          <v-col cols="6">
            <PosturePhoto :src="fileUrl(imageOf('before', v.value)?.url)" :label="`Before（${formatDate(pair.before.assessed_at)}）`" :grid="grid" />
          </v-col>
          <v-col cols="6">
            <PosturePhoto :src="fileUrl(imageOf('after', v.value)?.url)" :label="`After（${formatDate(pair.after.assessed_at)}）`" :grid="grid" />
          </v-col>
        </v-row>
      </v-card-text>
    </v-card>

    <v-card title="所見の比較">
      <v-table>
        <thead>
          <tr><th style="width: 160px" /><th>Before</th><th>After</th></tr>
        </thead>
        <tbody>
          <tr>
            <th>まとめ</th>
            <td class="pre">{{ pair.before.findings.overall_summary || '-' }}</td>
            <td class="pre">{{ pair.after.findings.overall_summary || '-' }}</td>
          </tr>
          <tr v-for="r in regions" :key="r.key">
            <th>{{ r.label }}</th>
            <td class="pre">{{ regionOf('before', r.key) || '-' }}</td>
            <td class="pre">{{ regionOf('after', r.key) || '-' }}</td>
          </tr>
        </tbody>
      </v-table>
    </v-card>
  </div>
  <v-alert v-else type="warning" variant="tonal" text="比較する姿勢評価が見つかりません。" />
</template>

<style scoped>
.pre {
  white-space: pre-wrap;
}
</style>
