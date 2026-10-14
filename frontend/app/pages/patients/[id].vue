<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

const route = useRoute()
const id = Number(route.params.id)
const api = useApi()

const { data: patient, refresh } = await useAsyncData(`patient-${id}`, async () => {
  const { data } = await api.GET('/api/patients/{patient_id}', {
    params: { path: { patient_id: id } },
  })
  return data ?? null
})
const { data: appointments, refresh: refreshAppts } = await useAsyncData(
  `patient-${id}-appts`,
  async () => {
    const { data } = await api.GET('/api/patients/{patient_id}/appointments', {
      params: { path: { patient_id: id } },
    })
    return data ?? []
  },
)
const { data: intakes, refresh: refreshIntakes } = await useAsyncData(
  `patient-${id}-intakes`,
  async () => {
    const { data } = await api.GET('/api/patients/{patient_id}/intakes', {
      params: { path: { patient_id: id } },
    })
    return data ?? []
  },
)

const editDialog = ref(false)
const editError = ref<string | null>(null)
async function update(body: Schemas['PatientUpdate']) {
  const { error } = await api.PUT('/api/patients/{patient_id}', {
    params: { path: { patient_id: id } },
    body,
  })
  if (error) {
    editError.value = errorMessage(error)
    return
  }
  editDialog.value = false
  await refresh()
}

const apptDialog = ref(false)
const editingAppt = ref<Schemas['AppointmentOut'] | null>(null)
function openAppt(a: Schemas['AppointmentOut'] | null) {
  editingAppt.value = a
  apptDialog.value = true
}

const intakeToken = ref<string | null>(null)
async function issueIntake() {
  const { data } = await api.POST('/api/intakes', { body: { patient_id: id } })
  if (data) {
    intakeToken.value = data.access_token
    await refreshIntakes()
  }
}
</script>

<template>
  <div v-if="patient">
    <PageHeader
      :title="patientName(patient)"
      :subtitle="`${patient.card_no} ・ ${patient.last_name_kana} ${patient.first_name_kana}`"
    >
      <v-btn variant="tonal" prepend-icon="mdi-pencil" @click="editDialog = true">編集</v-btn>
      <v-btn variant="tonal" prepend-icon="mdi-clipboard-text-outline" @click="issueIntake">
        問診URLを発行
      </v-btn>
      <v-btn color="primary" prepend-icon="mdi-calendar-plus" @click="openAppt(null)">
        予約を登録
      </v-btn>
    </PageHeader>

    <v-row>
      <v-col cols="12" md="4">
        <v-card title="基本情報">
          <v-list density="compact">
            <v-list-item title="生年月日" :subtitle="`${patient.birth_date}（${ageOf(patient.birth_date)}歳）`" />
            <v-list-item title="電話番号" :subtitle="patient.phone" />
            <v-list-item title="メール" :subtitle="patient.email || '-'" />
            <v-list-item title="住所" :subtitle="patient.address || '-'" />
            <v-list-item title="登録日" :subtitle="formatDate(patient.created_at)" />
          </v-list>
          <v-card-text v-if="patient.notes" class="pt-0">
            <div class="text-caption text-medium-emphasis">メモ</div>
            <div style="white-space: pre-wrap">{{ patient.notes }}</div>
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" md="8">
        <v-card title="予約履歴" class="mb-4">
          <v-table density="comfortable" hover>
            <thead>
              <tr>
                <th>日時</th>
                <th>メニュー</th>
                <th>担当</th>
                <th>ステータス</th>
              </tr>
            </thead>
            <tbody>
              <tr v-if="!appointments?.length">
                <td colspan="4" class="text-medium-emphasis">予約はありません</td>
              </tr>
              <tr
                v-for="a in appointments"
                :key="a.id"
                style="cursor: pointer"
                @click="openAppt(a)"
              >
                <td>{{ formatDateTime(a.start_at) }}</td>
                <td>{{ a.menu_name || '-' }}</td>
                <td>{{ a.assigned_staff?.full_name ?? '-' }}</td>
                <td>
                  <v-chip size="small" :color="STATUS_COLORS[a.status]" variant="flat">
                    {{ STATUS_LABELS[a.status] }}
                  </v-chip>
                </td>
              </tr>
            </tbody>
          </v-table>
        </v-card>

        <v-card title="問診">
          <v-list>
            <v-list-item v-if="!intakes?.length" subtitle="問診はありません" />
            <v-list-item
              v-for="i in intakes"
              :key="i.id"
              :to="i.submitted_at ? `/intakes/${i.id}` : undefined"
              :title="i.submitted_at ? i.chief_complaint : '未回答'"
              :subtitle="i.submitted_at ? `回答日時: ${formatDateTime(i.submitted_at)}` : `発行日時: ${formatDateTime(i.created_at)}`"
            >
              <template #append>
                <v-btn
                  v-if="!i.submitted_at"
                  size="small"
                  variant="text"
                  @click.prevent="intakeToken = i.access_token"
                >
                  URLを表示
                </v-btn>
              </template>
            </v-list-item>
          </v-list>
        </v-card>
      </v-col>
    </v-row>

    <v-dialog v-model="editDialog" max-width="880">
      <v-card title="患者情報の編集">
        <v-card-text>
          <v-alert v-if="editError" type="error" variant="tonal" class="mb-4" :text="editError" />
          <PatientForm :initial="patient" @submit="update">
            <template #actions>
              <v-btn variant="text" class="mr-2" @click="editDialog = false">キャンセル</v-btn>
            </template>
          </PatientForm>
        </v-card-text>
      </v-card>
    </v-dialog>

    <AppointmentDialog
      v-model="apptDialog"
      :appointment="editingAppt"
      :defaults="{ patient }"
      @saved="refreshAppts"
    />
    <IntakeLinkDialog :token="intakeToken" @close="intakeToken = null" />
  </div>
  <v-alert v-else type="warning" variant="tonal" text="患者が見つかりません。" />
</template>
