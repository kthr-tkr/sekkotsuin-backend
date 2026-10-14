<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

// 患者向け Web 問診（ログイン不要）
definePageMeta({ layout: 'public', public: true })

const route = useRoute()
const token = String(route.params.token)
const api = useApi()

const { data: intake, refresh } = await useAsyncData(`public-intake-${token}`, async () => {
  const { data } = await api.GET('/api/public/intakes/{token}', {
    params: { path: { token } },
  })
  return data ?? null
})

const form = reactive<Schemas['IntakeAnswers']>({
  chief_complaint: '',
  symptom_type: 'unknown',
  onset: '',
  pain_areas: [],
  pain_scale: null,
  cause: '',
  medical_history: '',
  medications: '',
  allergies: '',
  is_pregnant: null,
  notes: '',
  consent_agreed: false,
})
const painScale = ref(5)
const error = ref<string | null>(null)
const sending = ref(false)

const ONSETS = ['今日', '2〜3日前', '1週間前', '1ヶ月前', '半年以上前', 'わからない']
const required = (v: string) => !!v || '入力してください'

async function submit(e: Promise<{ valid: boolean }>) {
  if (!(await e).valid) return
  sending.value = true
  const { error: err } = await api.PUT('/api/public/intakes/{token}', {
    params: { path: { token } },
    body: { ...form, pain_scale: painScale.value },
  })
  sending.value = false
  if (err) {
    error.value = errorMessage(err)
    return
  }
  await refresh()
  window.scrollTo({ top: 0 })
}
</script>

<template>
  <div>
    <v-alert
      v-if="!intake"
      type="warning"
      variant="tonal"
      title="問診ページが見つかりません"
      text="URLの有効期限が切れているか、URLが正しくありません。お手数ですが院までお問い合わせください。"
    />

    <v-card v-else-if="intake.submitted" class="pa-4 text-center">
      <v-icon icon="mdi-check-circle" color="success" size="64" class="mb-2" />
      <v-card-title>ご回答ありがとうございました</v-card-title>
      <v-card-text>
        {{ intake.clinic_name }} にて内容を確認いたします。<br />
        ご来院をお待ちしております。
      </v-card-text>
    </v-card>

    <template v-else>
      <div class="mb-4">
        <div class="text-body-2 text-medium-emphasis">{{ intake.clinic_name }}</div>
        <h1 class="text-h5 font-weight-bold">Web問診票</h1>
        <div class="text-body-2">{{ intake.patient_display_name }}、ご来院前に以下にご回答ください。</div>
      </div>

      <v-form @submit.prevent="submit">
        <v-card class="mb-4" title="今のお悩みについて">
          <v-card-text>
            <v-text-field
              v-model="form.chief_complaint"
              label="一番気になる症状（例: 腰が痛い）"
              :rules="[required]"
            />
            <div class="text-subtitle-2 mb-1">痛む・気になる部位（複数選択可）</div>
            <v-chip-group v-model="form.pain_areas" multiple column selected-class="text-primary">
              <v-chip v-for="a in PAIN_AREAS" :key="a.value" :value="a.value" filter variant="outlined">
                {{ a.title }}
              </v-chip>
            </v-chip-group>
            <div class="text-subtitle-2 mt-4">痛みの強さ（0: 痛みなし 〜 10: 最も強い痛み）</div>
            <v-slider v-model="painScale" :min="0" :max="10" :step="1" thumb-label="always" class="mt-6" />
            <v-select v-model="form.onset" :items="ONSETS" label="いつから" />
            <v-radio-group v-model="form.symptom_type" inline label="症状の出かた">
              <v-radio label="急に（ケガ・ぎっくり等）" value="acute" />
              <v-radio label="以前から続いている" value="chronic" />
              <v-radio label="わからない" value="unknown" />
            </v-radio-group>
            <v-textarea v-model="form.cause" label="きっかけ・思い当たる原因（任意）" rows="2" auto-grow />
          </v-card-text>
        </v-card>

        <v-card class="mb-4" title="お体の状態について">
          <v-card-text>
            <v-textarea v-model="form.medical_history" label="これまでの病気・手術・ケガ（任意）" rows="2" auto-grow />
            <v-text-field v-model="form.medications" label="服用中のお薬（任意）" />
            <v-text-field v-model="form.allergies" label="アレルギー（任意）" />
            <v-radio-group v-model="form.is_pregnant" inline label="妊娠中または妊娠の可能性">
              <v-radio label="はい" :value="true" />
              <v-radio label="いいえ" :value="false" />
              <v-radio label="該当しない・回答しない" :value="null" />
            </v-radio-group>
            <v-textarea v-model="form.notes" label="その他、伝えておきたいこと（任意）" rows="2" auto-grow />
          </v-card-text>
        </v-card>

        <v-card class="mb-4">
          <v-card-text>
            <v-checkbox
              v-model="form.consent_agreed"
              label="入力した内容を施術のために院が利用することに同意します"
              :rules="[(v: boolean) => v || '同意が必要です']"
            />
            <v-alert v-if="error" type="error" variant="tonal" class="mb-4" :text="error" />
            <v-btn type="submit" color="primary" size="large" block :loading="sending">送信する</v-btn>
          </v-card-text>
        </v-card>
      </v-form>
    </template>
  </div>
</template>
