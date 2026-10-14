<script setup lang="ts">
const route = useRoute()
const id = Number(route.params.id)

const { data: intake } = await useAsyncData(`intake-${id}`, async () => {
  const { data } = await useApi().GET('/api/intakes/{intake_id}', {
    params: { path: { intake_id: id } },
  })
  return data ?? null
})

type Answers = {
  pain_areas?: string[]
  pain_scale?: number | null
  cause?: string
  medical_history?: string
  medications?: string
  allergies?: string
  is_pregnant?: boolean | null
  notes?: string
}
const answers = computed<Answers>(() => (intake.value?.payload?.answers as Answers) ?? {})
const areaLabel = (v: string) => PAIN_AREAS.find((a) => a.value === v)?.title ?? v
const yesNo = (v: boolean | null | undefined) => (v == null ? '-' : v ? 'はい' : 'いいえ')
</script>

<template>
  <div v-if="intake">
    <PageHeader
      :title="`問診: ${patientName(intake.patient)}`"
      :subtitle="intake.submitted_at ? `回答日時 ${formatDateTime(intake.submitted_at)}` : '未回答'"
    >
      <v-btn variant="tonal" :to="`/patients/${intake.patient_id}`">患者詳細</v-btn>
    </PageHeader>

    <v-card>
      <v-table>
        <tbody>
          <tr><th style="width: 200px">主訴</th><td>{{ intake.chief_complaint || '-' }}</td></tr>
          <tr><th>症状の種類</th><td>{{ SYMPTOM_LABELS[intake.symptom_type] }}</td></tr>
          <tr><th>いつから</th><td>{{ intake.onset || '-' }}</td></tr>
          <tr>
            <th>痛む部位</th>
            <td>
              <v-chip v-for="a in answers.pain_areas ?? []" :key="a" size="small" class="mr-1">
                {{ areaLabel(a) }}
              </v-chip>
              <span v-if="!answers.pain_areas?.length">-</span>
            </td>
          </tr>
          <tr><th>痛みの強さ（0〜10）</th><td>{{ answers.pain_scale ?? '-' }}</td></tr>
          <tr><th>きっかけ・原因</th><td class="pre">{{ answers.cause || '-' }}</td></tr>
          <tr><th>既往歴</th><td class="pre">{{ answers.medical_history || '-' }}</td></tr>
          <tr><th>服用中の薬</th><td class="pre">{{ answers.medications || '-' }}</td></tr>
          <tr><th>アレルギー</th><td class="pre">{{ answers.allergies || '-' }}</td></tr>
          <tr><th>妊娠の可能性</th><td>{{ yesNo(answers.is_pregnant) }}</td></tr>
          <tr><th>その他</th><td class="pre">{{ answers.notes || '-' }}</td></tr>
        </tbody>
      </v-table>
    </v-card>
  </div>
</template>

<style scoped>
.pre {
  white-space: pre-wrap;
}
</style>
