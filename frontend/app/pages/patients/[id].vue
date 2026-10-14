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

const { data: notes } = await useAsyncData(`patient-${id}-notes`, async () => {
  const { data } = await api.GET('/api/clinical-notes', {
    params: { query: { patient_id: id, limit: 20 } },
  })
  return data ?? { items: [], total: 0 }
})
const { data: plans } = await useAsyncData(`patient-${id}-plans`, async () => {
  const { data } = await api.GET('/api/treatment-plans', {
    params: { query: { patient_id: id, limit: 20 } },
  })
  return data ?? { items: [], total: 0 }
})
async function createPlan() {
  const { data } = await api.POST('/api/treatment-plans', { body: { patient_id: id } })
  if (data) await navigateTo(`/treatment-plans/${data.id}`)
}

const { data: postures } = await useAsyncData(`patient-${id}-postures`, async () => {
  const { data } = await api.GET('/api/posture-assessments', {
    params: { query: { patient_id: id, limit: 20 } },
  })
  return data ?? { items: [], total: 0 }
})
async function createPosture() {
  const { data } = await api.POST('/api/posture-assessments', { body: { patient_id: id } })
  if (data) await navigateTo(`/posture/${data.id}`)
}
const compareIds = ref<number[]>([])
async function compare() {
  // 撮影日時の古い方を Before にする（同じ日時なら先に作った方）
  const picked = (postures.value?.items ?? [])
    .filter((p) => compareIds.value.includes(p.id))
    .sort(
      (a, b) =>
        new Date(a.assessed_at).getTime() - new Date(b.assessed_at).getTime() || a.id - b.id,
    )
  if (picked.length === 2)
    await navigateTo(`/posture/compare?before=${picked[0]!.id}&after=${picked[1]!.id}`)
}

async function createNote() {
  const { data } = await api.POST('/api/clinical-notes', { body: { patient_id: id } })
  if (data) await navigateTo(`/clinical-notes/${data.id}`)
}

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

const issuedIntake = ref<{ id: number; access_token: string } | null>(null)
async function issueIntake() {
  const { data } = await api.POST('/api/intakes', { body: { patient_id: id } })
  if (data) {
    issuedIntake.value = data
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
            <div class="text-body-small text-medium-emphasis">メモ</div>
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

        <v-card title="カルテ" class="mb-4">
          <template #append>
            <v-btn size="small" variant="text" prepend-icon="mdi-plus" @click="createNote">
              予約なしで作成
            </v-btn>
          </template>
          <v-list>
            <v-list-item v-if="!notes?.items.length" subtitle="カルテはありません（予約のダイアログから作成できます）" />
            <v-list-item
              v-for="n in notes?.items"
              :key="n.id"
              :to="`/clinical-notes/${n.id}`"
              :title="`${formatDateTime(n.visited_at)}  ${n.practitioner?.full_name ?? ''}`"
              :subtitle="`PS ${n.pain_scale_before ?? '-'} → ${n.pain_scale_after ?? '-'} ／ ${n.subjective || n.assessment || '（記載なし）'}`"
            >
              <template #append>
                <v-chip size="small" :color="NOTE_STATUS_COLORS[n.status]" variant="flat">
                  {{ NOTE_STATUS_LABELS[n.status] }}
                </v-chip>
              </template>
            </v-list-item>
          </v-list>
        </v-card>

        <v-card title="施術計画" class="mb-4">
          <template #append>
            <v-btn size="small" variant="text" prepend-icon="mdi-plus" @click="createPlan">作成</v-btn>
          </template>
          <v-list>
            <v-list-item v-if="!plans?.items.length" subtitle="施術計画はありません" />
            <v-list-item
              v-for="pl in plans?.items"
              :key="pl.id"
              :to="`/treatment-plans/${pl.id}`"
              :title="pl.title || pl.chief_complaint || '（タイトル未設定）'"
              :subtitle="`${pl.start_date} 開始 ・ ${visitGuideText(pl) || '通院目安なし'}`"
            >
              <template #append>
                <v-chip size="small" :color="PLAN_STATUS_COLORS[pl.status]" variant="flat">
                  {{ PLAN_STATUS_LABELS[pl.status] }}
                </v-chip>
              </template>
            </v-list-item>
          </v-list>
        </v-card>

        <v-card title="姿勢評価" class="mb-4">
          <template #append>
            <v-btn
              size="small"
              variant="text"
              prepend-icon="mdi-compare-horizontal"
              :disabled="compareIds.length !== 2"
              @click="compare"
            >
              2件を比較
            </v-btn>
            <v-btn size="small" variant="text" prepend-icon="mdi-plus" @click="createPosture">作成</v-btn>
          </template>
          <v-list>
            <v-list-item v-if="!postures?.items.length" subtitle="姿勢評価はありません" />
            <v-list-item
              v-for="pa in postures?.items"
              :key="pa.id"
              :to="`/posture/${pa.id}`"
              :title="`${formatDateTime(pa.assessed_at)}  ${pa.title}`"
              :subtitle="`写真 ${pa.images.length}枚 ・ ${pa.findings.overall_summary || '所見未記入'}`"
            >
              <template #prepend>
                <v-checkbox-btn
                  :model-value="compareIds.includes(pa.id)"
                  :disabled="!compareIds.includes(pa.id) && compareIds.length >= 2"
                  aria-label="比較に使う"
                  @click.prevent.stop="compareIds = compareIds.includes(pa.id) ? compareIds.filter((x) => x !== pa.id) : [...compareIds, pa.id]"
                />
              </template>
              <template #append>
                <v-chip size="small" :color="pa.status === 'confirmed' ? 'success' : 'warning'" variant="flat">
                  {{ pa.status === 'confirmed' ? '確定' : '下書き' }}
                </v-chip>
              </template>
            </v-list-item>
          </v-list>
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
                  @click.prevent="issuedIntake = i"
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
    <IntakeLinkDialog :intake="issuedIntake" @close="issuedIntake = null" />
  </div>
  <v-alert v-else type="warning" variant="tonal" text="患者が見つかりません。" />
</template>
