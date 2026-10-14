<script setup lang="ts">
const route = useRoute()
const id = Number(route.params.id)

const { data: intake } = await useAsyncData(`intake-${id}`, async () => {
  const { data } = await useApi().GET('/api/intakes/{intake_id}', {
    params: { path: { intake_id: id } },
  })
  return data ?? null
})
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
      <IntakeAnswersTable :intake="intake" />
    </v-card>
  </div>
</template>
