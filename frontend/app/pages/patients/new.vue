<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

const error = ref<string | null>(null)

async function create(body: Schemas['PatientCreate']) {
  const { data, error: err } = await useApi().POST('/api/patients', { body })
  if (err || !data) {
    error.value = errorMessage(err)
    return
  }
  await navigateTo(`/patients/${data.id}`)
}
</script>

<template>
  <div>
    <PageHeader title="患者の新規登録" subtitle="診察券番号は自動で採番されます" />
    <v-card>
      <v-card-text>
        <v-alert v-if="error" type="error" variant="tonal" class="mb-4" :text="error" />
        <PatientForm submit-label="登録" @submit="create">
          <template #actions>
            <v-btn variant="text" class="mr-2" to="/patients">キャンセル</v-btn>
          </template>
        </PatientForm>
      </v-card-text>
    </v-card>
  </div>
</template>
