<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

type Appointment = Schemas['AppointmentOut']

const props = defineProps<{
  /** 編集時は既存予約、新規時は null */
  appointment: Appointment | null
  /** 新規時の初期値 */
  defaults?: { start_at?: string; end_at?: string; patient?: Schemas['PatientBrief'] | null }
}>()
const emit = defineEmits<{ close: []; saved: [] }>()

const open = defineModel<boolean>({ default: false })
const api = useApi()

const { data: menus } = await useAsyncData('menus-active', async () => {
  const { data } = await api.GET('/api/treatment-menus', { params: { query: { active_only: true } } })
  return data ?? []
})
const { data: staff } = await useAsyncData('staff', async () => {
  const { data } = await api.GET('/api/staff')
  return data ?? []
})

const form = reactive({
  patient_id: null as number | null,
  treatment_menu_id: null as number | null,
  start: '',
  end: '',
  assigned_staff_id: null as number | null,
  status: 'booked',
  booking_source: 'staff',
  notes: '',
})
const error = ref<string | null>(null)
const saving = ref(false)
const intakeToken = ref<string | null>(null)

watch(
  open,
  (v) => {
    if (!v) return
    error.value = null
    const a = props.appointment
    Object.assign(form, {
      patient_id: a?.patient_id ?? props.defaults?.patient?.id ?? null,
      treatment_menu_id: a?.treatment_menu_id ?? null,
      start: a ? isoToJstInput(a.start_at) : props.defaults?.start_at ? isoToJstInput(props.defaults.start_at) : '',
      end: a ? isoToJstInput(a.end_at) : props.defaults?.end_at ? isoToJstInput(props.defaults.end_at) : '',
      assigned_staff_id: a?.assigned_staff_id ?? null,
      status: a?.status ?? 'booked',
      booking_source: a?.booking_source ?? 'staff',
      notes: a?.notes ?? '',
    })
  },
  { immediate: true },
)

// メニュー選択時は所要時間から終了時刻を自動設定
watch(
  () => form.treatment_menu_id,
  (id, old) => {
    if (id === old || !id || !form.start) return
    const menu = menus.value?.find((m) => m.id === id)
    if (!menu) return
    const end = new Date(new Date(jstInputToIso(form.start)).getTime() + menu.duration_minutes * 60000)
    form.end = isoToJstInput(end.toISOString())
  },
)

const menuItems = computed(() =>
  (menus.value ?? []).map((m) => ({ value: m.id, title: `${m.name}（${m.duration_minutes}分）` })),
)
const staffItems = computed(() =>
  (staff.value ?? []).map((s) => ({ value: s.id, title: `${s.full_name}（${ROLE_LABELS[s.role]}）` })),
)
const initialPatient = computed(() => props.appointment?.patient ?? props.defaults?.patient ?? null)

async function save() {
  if (!form.start) {
    error.value = '開始日時を入力してください。'
    return
  }
  saving.value = true
  const body = {
    patient_id: form.patient_id,
    treatment_menu_id: form.treatment_menu_id,
    start_at: jstInputToIso(form.start),
    end_at: form.end ? jstInputToIso(form.end) : null,
    assigned_staff_id: form.assigned_staff_id,
    status: form.status as Appointment['status'],
    booking_source: form.booking_source as Appointment['booking_source'],
    notes: form.notes,
  }
  const res = props.appointment
    ? await api.PATCH('/api/appointments/{appt_id}', {
        params: { path: { appt_id: props.appointment.id } },
        body: { ...body, end_at: body.end_at ?? undefined },
      })
    : await api.POST('/api/appointments', { body })
  saving.value = false
  if (res.error) {
    error.value = errorMessage(res.error)
    return
  }
  open.value = false
  emit('saved')
}

async function remove() {
  if (!props.appointment || !confirm('この予約を削除しますか？（通常はステータスを「キャンセル」にしてください）')) return
  await api.DELETE('/api/appointments/{appt_id}', {
    params: { path: { appt_id: props.appointment.id } },
  })
  open.value = false
  emit('saved')
}

async function issueIntake() {
  const a = props.appointment
  if (!a?.patient_id) return
  const { data, error: err } = await api.POST('/api/intakes', {
    body: { patient_id: a.patient_id, appointment_id: a.id },
  })
  if (err || !data) {
    error.value = errorMessage(err)
    return
  }
  intakeToken.value = data.access_token
}
</script>

<template>
  <v-dialog v-model="open" max-width="720" @after-leave="emit('close')">
    <v-card :title="appointment ? '予約の編集' : '予約の登録'">
      <v-card-text>
        <v-alert v-if="error" type="error" variant="tonal" class="mb-4" :text="error" />
        <v-row density="compact">
          <v-col cols="12">
            <PatientPicker v-model="form.patient_id" :initial="initialPatient" />
          </v-col>
          <v-col cols="12" md="6">
            <v-select v-model="form.treatment_menu_id" :items="menuItems" label="施術メニュー" clearable />
          </v-col>
          <v-col cols="12" md="6">
            <v-select v-model="form.assigned_staff_id" :items="staffItems" label="担当者" clearable />
          </v-col>
          <v-col cols="12" md="6">
            <v-text-field v-model="form.start" type="datetime-local" label="開始" />
          </v-col>
          <v-col cols="12" md="6">
            <v-text-field
              v-model="form.end"
              type="datetime-local"
              label="終了"
              hint="空欄の場合はメニューの所要時間から自動設定"
              persistent-hint
            />
          </v-col>
          <v-col cols="12" md="6">
            <v-select v-model="form.status" :items="toItems(STATUS_LABELS)" label="ステータス" />
          </v-col>
          <v-col cols="12" md="6">
            <v-select v-model="form.booking_source" :items="toItems(BOOKING_SOURCE_LABELS)" label="予約経路" />
          </v-col>
          <v-col cols="12">
            <v-textarea v-model="form.notes" label="メモ" rows="2" auto-grow />
          </v-col>
        </v-row>
      </v-card-text>
      <v-card-actions>
        <template v-if="appointment">
          <v-btn color="error" variant="text" @click="remove">削除</v-btn>
          <v-btn
            v-if="appointment.patient_id"
            variant="text"
            prepend-icon="mdi-clipboard-text-outline"
            @click="issueIntake"
          >
            問診URL
          </v-btn>
          <v-btn
            v-if="appointment.patient_id"
            variant="text"
            :to="`/patients/${appointment.patient_id}`"
          >
            患者詳細
          </v-btn>
        </template>
        <v-spacer />
        <v-btn variant="text" @click="open = false">閉じる</v-btn>
        <v-btn color="primary" :loading="saving" @click="save">保存</v-btn>
      </v-card-actions>
    </v-card>
    <IntakeLinkDialog :token="intakeToken" @close="intakeToken = null" />
  </v-dialog>
</template>
