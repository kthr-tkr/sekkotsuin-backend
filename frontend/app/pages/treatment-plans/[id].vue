<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

type Plan = Schemas['TreatmentPlanOut']
type Form = Schemas['TreatmentPlanUpdate']

const route = useRoute()
const id = Number(route.params.id)
const api = useApi()
const tab = ref<'content' | 'progress' | 'consent'>('content')

const { data: plan } = await useAsyncData(`plan-${id}`, async () => {
  const { data } = await api.GET('/api/treatment-plans/{plan_id}', {
    params: { path: { plan_id: id } },
  })
  return data ?? null
})
const { data: progress } = await useAsyncData(`plan-${id}-progress`, async () => {
  const { data } = await api.GET('/api/treatment-plans/{plan_id}/progress', {
    params: { path: { plan_id: id } },
  })
  return data ?? []
})
const { data: consents, refresh: refreshConsents } = await useAsyncData(
  `plan-${id}-consents`,
  async () => {
    const { data } = await api.GET('/api/treatment-plans/{plan_id}/consents', {
      params: { path: { plan_id: id } },
    })
    return data ?? []
  },
)

const toForm = (p: Plan): Form => ({
  title: p.title ?? '',
  chief_complaint: p.chief_complaint ?? '',
  status: p.status,
  start_date: p.start_date,
  next_visit_date: p.next_visit_date ?? null,
  visit_guide_type: p.visit_guide_type ?? null,
  visit_guide_count: p.visit_guide_count ?? null,
  visit_guide_note: p.visit_guide_note ?? '',
  bath_instruction: p.bath_instruction ?? '',
  walking_instruction: p.walking_instruction ?? '',
  exercise_instruction: p.exercise_instruction ?? '',
  work_instruction: p.work_instruction ?? '',
  lifestyle_instruction: p.lifestyle_instruction ?? '',
  caution_notes: p.caution_notes ?? '',
  expected_recovery_weeks_min: p.expected_recovery_weeks_min ?? null,
  expected_recovery_weeks_max: p.expected_recovery_weeks_max ?? null,
  rebound_reaction_note: p.rebound_reaction_note ?? '',
})
const form = reactive(toForm(plan.value!))
const saved = ref(JSON.stringify(form))
const dirty = computed(() => JSON.stringify(form) !== saved.value)
const snackbar = ref<{ text: string; color: string } | null>(null)

const numOrNull = (v: unknown) => (v === '' || v == null ? null : Number(v))

async function save(): Promise<boolean> {
  const { data, error } = await api.PUT('/api/treatment-plans/{plan_id}', {
    params: { path: { plan_id: id } },
    body: {
      ...form,
      next_visit_date: form.next_visit_date || null,
      visit_guide_count: numOrNull(form.visit_guide_count),
      expected_recovery_weeks_min: numOrNull(form.expected_recovery_weeks_min),
      expected_recovery_weeks_max: numOrNull(form.expected_recovery_weeks_max),
    },
  })
  if (error || !data) {
    snackbar.value = { text: errorMessage(error), color: 'error' }
    return false
  }
  plan.value = data
  Object.assign(form, toForm(data))
  saved.value = JSON.stringify(form)
  snackbar.value = { text: '保存しました', color: 'success' }
  return true
}

onBeforeRouteLeave(() => {
  if (dirty.value && !confirm('保存していない変更があります。移動しますか？')) return false
})

// 同意サイン
const signDialog = ref(false)
const signedName = ref('')
const pad = ref<{ clear: () => void; toDataUrl: () => string; empty: boolean } | null>(null)
const signError = ref<string | null>(null)

async function openSign() {
  if (dirty.value && !(await save())) return
  signedName.value = plan.value ? patientName(plan.value.patient) : ''
  signError.value = null
  signDialog.value = true
}

async function submitSign() {
  if (!signedName.value) return (signError.value = 'お名前を入力してください。')
  if (!pad.value || pad.value.empty) return (signError.value = 'サインを書いてください。')
  const { error } = await api.POST('/api/treatment-plans/{plan_id}/consents', {
    params: { path: { plan_id: id } },
    body: { signed_name: signedName.value, signature_data_url: pad.value.toDataUrl() },
  })
  if (error) return (signError.value = errorMessage(error))
  signDialog.value = false
  const { data } = await api.GET('/api/treatment-plans/{plan_id}', {
    params: { path: { plan_id: id } },
  })
  plan.value = data ?? plan.value
  await refreshConsents()
  snackbar.value = { text: 'サインを保存しました', color: 'success' }
}

const chartPoints = computed(() =>
  (progress.value ?? []).map((n) => ({
    date: isoToJstInput(n.visited_at).slice(0, 10),
    before: n.pain_scale_before ?? null,
    after: n.pain_scale_after ?? null,
  })),
)
const guideItems = toItems(VISIT_GUIDE_LABELS)
</script>

<template>
  <div v-if="plan">
    <PageHeader
      :title="`施術計画: ${patientName(plan.patient)}`"
      :subtitle="`${plan.patient.card_no} ・ ${plan.start_date} 開始${plan.end_date ? ` 〜 ${plan.end_date}` : ''}`"
    >
      <v-chip :color="PLAN_STATUS_COLORS[plan.status]" variant="flat">
        {{ PLAN_STATUS_LABELS[plan.status] }}
      </v-chip>
      <v-chip
        v-if="plan.latest_consent && !plan.consent_outdated"
        color="success"
        variant="tonal"
        prepend-icon="mdi-draw-pen"
      >
        同意済み
      </v-chip>
      <v-chip v-else color="warning" variant="tonal" prepend-icon="mdi-alert-outline">
        {{ plan.consent_outdated ? '内容変更後の再同意が必要' : '未同意' }}
      </v-chip>
      <v-btn variant="tonal" :to="`/patients/${plan.patient_id}`">患者詳細</v-btn>
      <v-btn color="primary" :disabled="!dirty" @click="save">保存</v-btn>
    </PageHeader>

    <v-card>
      <v-tabs v-model="tab" color="primary">
        <v-tab value="content">計画内容</v-tab>
        <v-tab value="progress">経過（{{ progress?.length ?? 0 }}回）</v-tab>
        <v-tab value="consent">説明・同意</v-tab>
      </v-tabs>
      <v-divider />

      <v-tabs-window v-model="tab">
        <v-tabs-window-item value="content">
          <v-card-text>
            <v-row density="compact">
              <v-col cols="12" md="6"><v-text-field v-model="form.title" label="計画タイトル" /></v-col>
              <v-col cols="12" md="6"><v-text-field v-model="form.chief_complaint" label="主訴" /></v-col>
              <v-col cols="6" md="3"><v-text-field v-model="form.start_date" type="date" label="開始日" /></v-col>
              <v-col cols="6" md="3">
                <v-text-field v-model="form.next_visit_date" type="date" label="次回来院日" clearable />
              </v-col>
              <v-col cols="12" md="6">
                <v-select v-model="form.status" :items="toItems(PLAN_STATUS_LABELS)" label="ステータス" />
              </v-col>
              <v-col cols="6" md="3">
                <v-select v-model="form.visit_guide_type" :items="guideItems" label="通院の目安" clearable />
              </v-col>
              <v-col cols="6" md="3">
                <v-text-field
                  v-model="form.visit_guide_count"
                  type="number"
                  label="回数"
                  :disabled="form.visit_guide_type !== 'weekly' && form.visit_guide_type !== 'monthly'"
                />
              </v-col>
              <v-col cols="12" md="6">
                <v-text-field v-model="form.visit_guide_note" label="通院の目安（補足）" placeholder="例: 痛みが落ち着くまで" />
              </v-col>
              <v-col cols="6" md="3">
                <v-text-field v-model="form.expected_recovery_weeks_min" type="number" label="改善目安（最短・週）" />
              </v-col>
              <v-col cols="6" md="3">
                <v-text-field v-model="form.expected_recovery_weeks_max" type="number" label="改善目安（最長・週）" />
              </v-col>
              <v-col v-for="f in PLAN_INSTRUCTIONS" :key="f.key" cols="12" md="6">
                <v-textarea v-model="form[f.key]" :label="f.label" rows="2" auto-grow />
              </v-col>
              <v-col cols="12">
                <v-textarea v-model="form.rebound_reaction_note" label="好転反応についての説明" rows="2" auto-grow />
              </v-col>
            </v-row>
          </v-card-text>
        </v-tabs-window-item>

        <v-tabs-window-item value="progress">
          <v-card-text>
            <p v-if="!progress?.length" class="text-medium-emphasis">
              計画の開始日以降のカルテが、ここに経過として表示されます。
            </p>
            <template v-else>
              <h3 class="text-subtitle-1 font-weight-bold mb-2">痛み（PS）の推移</h3>
              <PainTrendChart :points="chartPoints" class="mb-4" />
              <v-table density="comfortable" hover>
                <thead>
                  <tr>
                    <th>来院日</th>
                    <th>施術前PS</th>
                    <th>施術後PS</th>
                    <th>S（主観）</th>
                    <th>施術内容</th>
                    <th>担当</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="n in progress"
                    :key="n.id"
                    style="cursor: pointer"
                    @click="navigateTo(`/clinical-notes/${n.id}`)"
                  >
                    <td>{{ formatDate(n.visited_at) }}</td>
                    <td>{{ n.pain_scale_before ?? '-' }}</td>
                    <td>{{ n.pain_scale_after ?? '-' }}</td>
                    <td>{{ n.subjective || '-' }}</td>
                    <td>{{ n.treatment_content || '-' }}</td>
                    <td>{{ n.practitioner?.full_name ?? '-' }}</td>
                  </tr>
                </tbody>
              </v-table>
            </template>
          </v-card-text>
        </v-tabs-window-item>

        <v-tabs-window-item value="consent">
          <v-card-text>
            <v-alert
              v-if="plan.consent_outdated"
              type="warning"
              variant="tonal"
              class="mb-4"
              text="最後に同意をもらった後で計画の内容が変わっています。患者さんに説明し、改めてサインをもらってください。"
            />
            <div class="d-flex justify-end mb-4">
              <v-btn color="primary" prepend-icon="mdi-draw-pen" @click="openSign">
                患者さんに説明してサインをもらう
              </v-btn>
            </div>
            <p v-if="!consents?.length" class="text-medium-emphasis">まだ同意のサインはありません。</p>
            <v-card v-for="c in consents" :key="c.id" variant="outlined" class="mb-3">
              <v-card-title class="text-subtitle-1">
                {{ formatDateTime(c.signed_at) }}　{{ c.signed_name }} 様
              </v-card-title>
              <v-card-subtitle>立ち会い: {{ c.witnessed_by?.full_name ?? '-' }}</v-card-subtitle>
              <v-card-text>
                <v-img :src="fileUrl(c.signature_url)" max-width="360" class="border rounded mb-2" />
                <v-expansion-panels>
                  <v-expansion-panel title="同意した計画の内容">
                    <v-expansion-panel-text><PlanSummary :plan="c.plan_snapshot" /></v-expansion-panel-text>
                  </v-expansion-panel>
                </v-expansion-panels>
              </v-card-text>
            </v-card>
          </v-card-text>
        </v-tabs-window-item>
      </v-tabs-window>
    </v-card>

    <!-- 患者さんに見せる画面（院内のタブレットで署名） -->
    <v-dialog v-model="signDialog" fullscreen>
      <v-card>
        <v-toolbar color="primary" title="施術計画のご説明と同意">
          <v-btn icon="mdi-close" @click="signDialog = false" />
        </v-toolbar>
        <v-container style="max-width: 760px">
          <p class="mb-4">
            {{ patientName(plan.patient) }} 様の施術計画です。内容をご確認のうえ、ご同意いただける場合はサインをお願いします。
          </p>
          <v-card variant="outlined" class="mb-4"><PlanSummary :plan="plan" /></v-card>
          <v-text-field v-model="signedName" label="お名前" />
          <SignaturePad ref="pad" />
          <v-alert v-if="signError" type="error" variant="tonal" class="mt-3" :text="signError" />
          <v-btn color="primary" size="x-large" block class="mt-4" @click="submitSign">
            上記の内容に同意してサインする
          </v-btn>
        </v-container>
      </v-card>
    </v-dialog>

    <v-snackbar :model-value="!!snackbar" :color="snackbar?.color" @update:model-value="snackbar = null">
      {{ snackbar?.text }}
    </v-snackbar>
  </div>
  <v-alert v-else type="warning" variant="tonal" text="施術計画が見つかりません。" />
</template>
