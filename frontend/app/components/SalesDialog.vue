<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

type Sales = Schemas['SalesOut']
type Body = Schemas['SalesCreate']

const props = defineProps<{
  /** 編集する売上（新規なら null） */
  record: Sales | null
  /** 新規時の初期値（カルテから作る場合など） */
  draft?: Body | null
  patient?: Schemas['PatientBrief'] | null
}>()
const emit = defineEmits<{ saved: [] }>()
const open = defineModel<boolean>({ default: false })
const api = useApi()

const { data: menus } = await useAsyncData('menus-all', async () => {
  const { data } = await api.GET('/api/treatment-menus')
  return data ?? []
})
const { data: staff } = await useAsyncData('staff', async () => {
  const { data } = await api.GET('/api/staff')
  return data ?? []
})

const empty = (): Body => ({
  patient_id: 0,
  treatment_date: currentMonth() + '-01',
  amount: 0,
  description: '',
  payment_method: 'cash',
  status: 'paid',
  memo: '',
  appointment_id: null,
  clinical_note_id: null,
  treatment_menu_id: null,
  staff_id: null,
})
const form = reactive<Body>(empty())
const error = ref<string | null>(null)

watch(
  open,
  (v) => {
    if (!v) return
    error.value = null
    const src = props.record ?? props.draft
    Object.assign(form, empty(), src ? { ...src } : {})
    if (!src) form.treatment_date = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Tokyo' }).format(new Date())
  },
  { immediate: true },
)

// メニューを選ぶと料金と明細を入れる
watch(
  () => form.treatment_menu_id,
  (id, old) => {
    if (!id || id === old || !open.value) return
    const m = menus.value?.find((x) => x.id === id)
    if (m) {
      form.amount = m.price
      form.description = m.name
    }
  },
)

async function save() {
  if (!form.patient_id) {
    error.value = '患者を選択してください。'
    return
  }
  const body = { ...form, amount: Number(form.amount) }
  const res = props.record
    ? await api.PUT('/api/sales/{record_id}', { params: { path: { record_id: props.record.id } }, body })
    : await api.POST('/api/sales', { body })
  if (res.error) {
    error.value = errorMessage(res.error)
    return
  }
  open.value = false
  emit('saved')
}

const menuItems = computed(() =>
  (menus.value ?? []).map((m) => ({ value: m.id, title: `${m.name}（${yen(m.price)}）` })),
)
const staffItems = computed(() => (staff.value ?? []).map((s) => ({ value: s.id, title: s.full_name })))
const initialPatient = computed(() => props.record?.patient ?? props.patient ?? null)
</script>

<template>
  <v-dialog v-model="open" max-width="640">
    <v-card :title="record ? '会計の編集' : '会計の登録'">
      <v-card-text>
        <v-alert v-if="error" type="error" variant="tonal" class="mb-4" :text="error" />
        <PatientPicker v-model="form.patient_id" :initial="initialPatient" />
        <v-row density="compact">
          <v-col cols="12" md="6">
            <v-text-field v-model="form.treatment_date" type="date" label="施術日" />
          </v-col>
          <v-col cols="12" md="6">
            <v-select v-model="form.staff_id" :items="staffItems" label="担当" clearable />
          </v-col>
          <v-col cols="12" md="6">
            <v-select v-model="form.treatment_menu_id" :items="menuItems" label="施術メニュー" clearable />
          </v-col>
          <v-col cols="12" md="6">
            <v-text-field v-model="form.description" label="明細" />
          </v-col>
          <v-col cols="12" md="4">
            <v-text-field v-model.number="form.amount" type="number" label="金額（税込）" suffix="円" />
          </v-col>
          <v-col cols="12" md="4">
            <v-select v-model="form.payment_method" :items="toItems(PAYMENT_LABELS)" label="支払方法" />
          </v-col>
          <v-col cols="12" md="4">
            <v-select v-model="form.status" :items="toItems(SALES_STATUS_LABELS)" label="状態" />
          </v-col>
          <v-col cols="12">
            <v-textarea v-model="form.memo" label="メモ" rows="2" auto-grow />
          </v-col>
        </v-row>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn variant="text" @click="open = false">閉じる</v-btn>
        <v-btn color="primary" @click="save">保存</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
