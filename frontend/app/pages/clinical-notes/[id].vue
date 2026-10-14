<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

type Note = Schemas['ClinicalNoteOut']

const route = useRoute()
const id = Number(route.params.id)
const api = useApi()

const { data: note } = await useAsyncData(`clinical-note-${id}`, async () => {
  const { data } = await api.GET('/api/clinical-notes/{note_id}', {
    params: { path: { note_id: id } },
  })
  return data ?? null
})
const { data: staff } = await useAsyncData('staff', async () => {
  const { data } = await api.GET('/api/staff')
  return data ?? []
})
const { data: intake } = await useAsyncData(`clinical-note-${id}-intake`, async () => {
  if (!note.value?.intake_id) return null
  const { data } = await api.GET('/api/intakes/{intake_id}', {
    params: { path: { intake_id: note.value.intake_id } },
  })
  return data ?? null
})
// 同じ患者の過去のカルテ（直近5件）
const { data: history } = await useAsyncData(`clinical-note-${id}-history`, async () => {
  if (!note.value) return []
  const { data } = await api.GET('/api/clinical-notes', {
    params: { query: { patient_id: note.value.patient_id, limit: 6 } },
  })
  return (data?.items ?? []).filter((n) => n.id !== id).slice(0, 5)
})

type Form = Schemas['ClinicalNoteUpdate']
const toForm = (n: Note): Form & { visited_local: string } => ({
  visited_at: n.visited_at,
  visited_local: isoToJstInput(n.visited_at),
  practitioner_id: n.practitioner_id ?? null,
  subjective: n.subjective ?? '',
  objective: n.objective ?? '',
  assessment: n.assessment ?? '',
  plan: n.plan ?? '',
  treatment_content: n.treatment_content ?? '',
  precautions: n.precautions ?? '',
  next_visit_suggestion: n.next_visit_suggestion ?? '',
  pain_scale_before: n.pain_scale_before ?? null,
  pain_scale_after: n.pain_scale_after ?? null,
})
const form = reactive(toForm(note.value!))
const saved = ref(JSON.stringify(form))
const dirty = computed(() => JSON.stringify(form) !== saved.value)

const snackbar = ref<{ text: string; color: string } | null>(null)
const saving = ref(false)

async function save(): Promise<boolean> {
  saving.value = true
  const { visited_local, ...rest } = form
  const { data, error } = await api.PUT('/api/clinical-notes/{note_id}', {
    params: { path: { note_id: id } },
    body: { ...rest, visited_at: jstInputToIso(visited_local) },
  })
  saving.value = false
  if (error || !data) {
    snackbar.value = { text: errorMessage(error), color: 'error' }
    return false
  }
  note.value = data
  Object.assign(form, toForm(data))
  saved.value = JSON.stringify(form)
  snackbar.value = { text: '保存しました', color: 'success' }
  return true
}

async function finalize() {
  if (!confirm('カルテを確定しますか？予約は「完了」になります。確定後も修正はできますが、修正履歴が残ります。')) return
  if (dirty.value && !(await save())) return
  const { data, error } = await api.POST('/api/clinical-notes/{note_id}/finalize', {
    params: { path: { note_id: id } },
  })
  if (error || !data) {
    snackbar.value = { text: errorMessage(error), color: 'error' }
    return
  }
  note.value = data
  snackbar.value = { text: 'カルテを確定しました', color: 'success' }
}

// 修正履歴
const revisionsDialog = ref(false)
const { data: revisions, refresh: loadRevisions } = await useAsyncData(
  `clinical-note-${id}-revisions`,
  async () => {
    const { data } = await api.GET('/api/clinical-notes/{note_id}/revisions', {
      params: { path: { note_id: id } },
    })
    return data ?? []
  },
  { immediate: false },
)
async function openRevisions() {
  await loadRevisions()
  revisionsDialog.value = true
}
const FIELD_LABELS: Record<string, string> = {
  ...Object.fromEntries(SOAP_FIELDS.map((f) => [f.key, f.label])),
  treatment_content: '施術内容',
  precautions: '注意事項・生活指導',
  next_visit_suggestion: '次回来院の目安',
  pain_scale_before: '施術前PS',
  pain_scale_after: '施術後PS',
  visited_at: '来院日時',
  practitioner_id: '担当者',
  status: '状態',
}

onBeforeRouteLeave(() => {
  if (dirty.value && !confirm('保存していない変更があります。移動しますか？')) return false
})

const staffItems = computed(() =>
  (staff.value ?? []).map((s) => ({ value: s.id, title: s.full_name })),
)
const print = () => window.print()
const psItems = Array.from({ length: 11 }, (_, i) => ({ value: i, title: String(i) }))
</script>

<template>
  <div v-if="note">
    <PageHeader
      :title="`カルテ: ${patientName(note.patient)}`"
      :subtitle="`${note.patient.card_no} ・ 来院 ${formatDateTime(note.visited_at)}`"
    >
      <v-chip :color="NOTE_STATUS_COLORS[note.status]" variant="flat">
        {{ NOTE_STATUS_LABELS[note.status] }}
      </v-chip>
      <v-btn variant="text" prepend-icon="mdi-history" class="d-print-none" @click="openRevisions">
        修正履歴
      </v-btn>
      <v-btn variant="text" prepend-icon="mdi-printer" class="d-print-none" @click="print">
        印刷
      </v-btn>
      <v-btn variant="tonal" class="d-print-none" :to="`/patients/${note.patient_id}`">患者詳細</v-btn>
      <v-btn variant="tonal" color="primary" class="d-print-none" :loading="saving" :disabled="!dirty" @click="save">
        保存
      </v-btn>
      <v-btn
        v-if="note.status === 'draft'"
        color="success"
        class="d-print-none"
        prepend-icon="mdi-check"
        @click="finalize"
      >
        確定
      </v-btn>
    </PageHeader>

    <v-row>
      <v-col cols="12" lg="8">
        <v-card class="mb-4">
          <v-card-text>
            <v-row density="compact">
              <v-col cols="12" md="6">
                <v-text-field v-model="form.visited_local" type="datetime-local" label="来院日時" />
              </v-col>
              <v-col cols="12" md="6">
                <v-select v-model="form.practitioner_id" :items="staffItems" label="担当者" clearable />
              </v-col>
              <v-col cols="6" md="3">
                <v-select v-model="form.pain_scale_before" :items="psItems" label="施術前PS" clearable />
              </v-col>
              <v-col cols="6" md="3">
                <v-select v-model="form.pain_scale_after" :items="psItems" label="施術後PS" clearable />
              </v-col>
              <v-col cols="12" md="6">
                <v-text-field
                  v-model="form.next_visit_suggestion"
                  label="次回来院の目安"
                  placeholder="例: 3日後"
                  counter="100"
                />
              </v-col>
            </v-row>
          </v-card-text>
        </v-card>

        <v-card title="SOAP" class="mb-4">
          <v-card-text>
            <v-textarea
              v-for="f in SOAP_FIELDS"
              :key="f.key"
              v-model="form[f.key]"
              :label="f.label"
              :hint="f.hint"
              rows="3"
              auto-grow
              class="mb-1"
            />
          </v-card-text>
        </v-card>

        <v-card title="施術・指導" class="mb-4">
          <v-card-text>
            <v-textarea
              v-model="form.treatment_content"
              label="施術内容"
              hint="例: 腰部 手技 15分、低周波 10分"
              rows="3"
              auto-grow
            />
            <v-textarea v-model="form.precautions" label="注意事項・生活指導" rows="2" auto-grow />
          </v-card-text>
        </v-card>
      </v-col>

      <v-col cols="12" lg="4" class="d-print-none">
        <v-card v-if="intake" title="今回の問診" class="mb-4">
          <IntakeAnswersTable :intake="intake" density="compact" />
        </v-card>

        <v-card title="過去のカルテ">
          <v-list>
            <v-list-item v-if="!history?.length" subtitle="過去のカルテはありません" />
            <v-list-item
              v-for="h in history"
              :key="h.id"
              :to="`/clinical-notes/${h.id}`"
              :title="formatDateTime(h.visited_at)"
              lines="three"
            >
              <v-list-item-subtitle>
                PS {{ h.pain_scale_before ?? '-' }} → {{ h.pain_scale_after ?? '-' }} ／
                {{ h.subjective || h.assessment || '（記載なし）' }}
              </v-list-item-subtitle>
            </v-list-item>
          </v-list>
        </v-card>
      </v-col>
    </v-row>

    <v-dialog v-model="revisionsDialog" max-width="760">
      <v-card title="修正履歴" subtitle="各時点で保存される前の内容です">
        <v-card-text>
          <p v-if="!revisions?.length" class="text-medium-emphasis">修正履歴はありません</p>
          <v-expansion-panels v-else>
            <v-expansion-panel
              v-for="r in revisions"
              :key="r.id"
              :title="`${formatDateTime(r.created_at)} に ${r.edited_by?.full_name ?? '不明'} が修正`"
            >
              <v-expansion-panel-text>
                <v-table density="compact">
                  <tbody>
                    <tr v-for="(v, k) in r.snapshot" :key="k">
                      <th style="width: 160px">{{ FIELD_LABELS[k] ?? k }}</th>
                      <td style="white-space: pre-wrap">
                        {{ k === 'visited_at' ? formatDateTime(String(v)) : v ?? '-' }}
                      </td>
                    </tr>
                  </tbody>
                </v-table>
              </v-expansion-panel-text>
            </v-expansion-panel>
          </v-expansion-panels>
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn @click="revisionsDialog = false">閉じる</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar :model-value="!!snackbar" :color="snackbar?.color" @update:model-value="snackbar = null">
      {{ snackbar?.text }}
    </v-snackbar>
  </div>
  <v-alert v-else type="warning" variant="tonal" text="カルテが見つかりません。" />
</template>
