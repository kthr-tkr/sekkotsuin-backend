<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

type Assessment = Schemas['PostureOut']

const route = useRoute()
const id = Number(route.params.id)
const api = useApi()

const { data: assessment } = await useAsyncData(`posture-${id}`, async () => {
  const { data } = await api.GET('/api/posture-assessments/{assessment_id}', {
    params: { path: { assessment_id: id } },
  })
  return data ?? null
})

const toForm = (a: Assessment) => ({
  title: a.title,
  assessed_local: isoToJstInput(a.assessed_at),
  memo: a.memo ?? '',
  overall_summary: a.findings.overall_summary ?? '',
  important_points: (a.findings.important_points ?? []).join('\n'),
  regions: { ...a.findings.regions } as Record<string, string>,
})
const form = reactive(toForm(assessment.value!))
const saved = ref(JSON.stringify(form))
const dirty = computed(() => JSON.stringify(form) !== saved.value)
const snackbar = ref<{ text: string; color: string } | null>(null)
const grid = ref(true)

function apply(data: Assessment) {
  assessment.value = data
}

async function save(): Promise<boolean> {
  const { data, error } = await api.PUT('/api/posture-assessments/{assessment_id}', {
    params: { path: { assessment_id: id } },
    body: {
      title: form.title,
      assessed_at: jstInputToIso(form.assessed_local),
      memo: form.memo,
      findings: {
        overall_summary: form.overall_summary,
        important_points: form.important_points.split('\n').map((s) => s.trim()).filter(Boolean),
        regions: form.regions as Schemas['PostureRegions'],
      },
    },
  })
  if (error || !data) {
    snackbar.value = { text: errorMessage(error), color: 'error' }
    return false
  }
  apply(data)
  Object.assign(form, toForm(data))
  saved.value = JSON.stringify(form)
  snackbar.value = { text: '保存しました', color: 'success' }
  return true
}

async function confirmAssessment() {
  if (dirty.value && !(await save())) return
  const { data } = await api.POST('/api/posture-assessments/{assessment_id}/confirm', {
    params: { path: { assessment_id: id } },
  })
  if (data) {
    apply(data)
    snackbar.value = { text: '確定しました', color: 'success' }
  }
}

// 写真
const uploading = ref<string | null>(null)
const inputs = ref<Record<string, HTMLInputElement | null>>({})
type View = Schemas['PostureImageOut']['view']

async function upload(view: View, e: Event) {
  const file = (e.target as HTMLInputElement).files?.[0]
  if (!file) return
  uploading.value = view
  const fd = new FormData()
  fd.append('file', file)
  const { data, error } = await api.PUT('/api/posture-assessments/{assessment_id}/images/{view}', {
    params: { path: { assessment_id: id, view } },
    body: fd as unknown as { file: string },
    bodySerializer: (b) => b as unknown as FormData,
  })
  uploading.value = null
  ;(e.target as HTMLInputElement).value = ''
  if (error || !data) {
    snackbar.value = { text: errorMessage(error), color: 'error' }
    return
  }
  apply(data)
}

async function removeImage(view: View) {
  if (!confirm('この写真を削除しますか？')) return
  const { data } = await api.DELETE('/api/posture-assessments/{assessment_id}/images/{view}', {
    params: { path: { assessment_id: id, view } },
  })
  if (data) apply(data)
}

const imageOf = (view: string) => assessment.value?.images.find((i) => i.view === view)

onBeforeRouteLeave(() => {
  if (dirty.value && !confirm('保存していない変更があります。移動しますか？')) return false
})
</script>

<template>
  <div v-if="assessment">
    <PageHeader
      :title="`姿勢評価: ${patientName(assessment.patient)}`"
      :subtitle="`${assessment.patient.card_no} ・ ${formatDateTime(assessment.assessed_at)}`"
    >
      <v-chip :color="assessment.status === 'confirmed' ? 'success' : 'warning'" variant="flat">
        {{ assessment.status === 'confirmed' ? '確定' : '下書き' }}
      </v-chip>
      <v-switch v-model="grid" label="グリッド線" color="primary" hide-details density="compact" class="flex-grow-0" />
      <v-btn variant="tonal" :to="`/patients/${assessment.patient_id}`">患者詳細</v-btn>
      <v-btn color="primary" :disabled="!dirty" @click="save">保存</v-btn>
      <v-btn v-if="assessment.status === 'draft'" color="success" prepend-icon="mdi-check" @click="confirmAssessment">
        確定
      </v-btn>
    </PageHeader>

    <v-card class="mb-4">
      <v-card-text>
        <v-row>
          <v-col v-for="v in POSTURE_VIEWS" :key="v.value" cols="6" md="3">
            <PosturePhoto :src="fileUrl(imageOf(v.value)?.url)" :label="v.title" :grid="grid">
              <div class="d-flex ga-1 mt-2">
                <v-btn
                  size="small"
                  variant="tonal"
                  color="primary"
                  prepend-icon="mdi-camera"
                  :loading="uploading === v.value"
                  class="flex-grow-1"
                  @click="inputs[v.value]?.click()"
                >
                  {{ imageOf(v.value) ? '撮り直す' : '撮影・選択' }}
                </v-btn>
                <v-btn
                  v-if="imageOf(v.value)"
                  size="small"
                  variant="text"
                  icon="mdi-delete-outline"
                  :aria-label="`${v.title}の写真を削除`"
                  @click="removeImage(v.value)"
                />
              </div>
              <input
                :ref="(el) => (inputs[v.value] = el as HTMLInputElement | null)"
                type="file"
                accept="image/jpeg,image/png,image/webp"
                capture="environment"
                hidden
                @change="upload(v.value, $event)"
              />
            </PosturePhoto>
          </v-col>
        </v-row>
        <p class="text-caption text-medium-emphasis mt-2">
          写真は保存時に位置情報（EXIF）を取り除き、長辺 2000px に縮小しています。
        </p>
      </v-card-text>
    </v-card>

    <v-row>
      <v-col cols="12" md="5">
        <v-card title="基本情報" class="mb-4">
          <v-card-text>
            <v-text-field v-model="form.title" label="タイトル" />
            <v-text-field v-model="form.assessed_local" type="datetime-local" label="撮影日時" />
            <v-textarea v-model="form.memo" label="メモ（撮影時の状況・主訴など）" rows="2" auto-grow />
          </v-card-text>
        </v-card>
        <v-card title="全体所見">
          <v-card-text>
            <v-textarea v-model="form.overall_summary" label="まとめ" rows="3" auto-grow />
            <v-textarea
              v-model="form.important_points"
              label="重要ポイント（1行に1つ）"
              rows="3"
              auto-grow
              placeholder="頭部前方位&#10;右肩の下制"
            />
          </v-card-text>
        </v-card>
      </v-col>
      <v-col cols="12" md="7">
        <v-card title="部位別の所見">
          <v-card-text>
            <v-row density="compact">
              <v-col v-for="r in POSTURE_REGIONS" :key="r.key" cols="12" sm="6">
                <v-textarea v-model="form.regions[r.key]" :label="r.label" rows="2" auto-grow />
              </v-col>
            </v-row>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>

    <v-snackbar :model-value="!!snackbar" :color="snackbar?.color" @update:model-value="snackbar = null">
      {{ snackbar?.text }}
    </v-snackbar>
  </div>
  <v-alert v-else type="warning" variant="tonal" text="姿勢評価が見つかりません。" />
</template>
