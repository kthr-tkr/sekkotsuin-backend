<script setup lang="ts">
import FullCalendar from '@fullcalendar/vue3'
import type {
  CalendarOptions,
  DateSelectInfo,
  DatesSetInfo,
  EventClickInfo,
  EventChangeInfo,
  EventInput,
} from '@fullcalendar/vue3'
import classicTheme from '@fullcalendar/vue3/themes/classic'
import timeGridPlugin from '@fullcalendar/vue3/timegrid'
import dayGridPlugin from '@fullcalendar/vue3/daygrid'
import interactionPlugin from '@fullcalendar/vue3/interaction'
import jaLocale from '@fullcalendar/vue3/locales/ja'
import '@fullcalendar/vue3/skeleton.css'
import '@fullcalendar/vue3/themes/classic/theme.css'
import '@fullcalendar/vue3/themes/classic/palette.css'
import type { Schemas } from '~/composables/useApi'

type Appointment = Schemas['AppointmentOut']

const api = useApi()

const { data: settings } = await useAsyncData('clinic-settings', async () => {
  const { data } = await api.GET('/api/clinic/settings')
  return data ?? null
})
const { data: staff } = await useAsyncData('staff', async () => {
  const { data } = await api.GET('/api/staff')
  return data ?? []
})

const staffFilter = ref<number | null>(null)
const range = ref<{ start: string; end: string } | null>(null)
const appointments = ref<Appointment[]>([])
const snackbar = ref<string | null>(null)

async function load() {
  if (!range.value) return
  const { data } = await api.GET('/api/appointments', {
    params: {
      query: {
        start: range.value.start,
        end: range.value.end,
        staff_id: staffFilter.value ?? undefined,
      },
    },
  })
  appointments.value = data ?? []
}
watch(staffFilter, load)

const events = computed<EventInput[]>(() =>
  appointments.value.map((a) => ({
    id: String(a.id),
    title: `${patientName(a.patient)}${a.menu_name ? ` / ${a.menu_name}` : ''}${a.assigned_staff ? ` (${a.assigned_staff.full_name})` : ''}`,
    start: a.start_at,
    end: a.end_at,
    color: STATUS_COLORS[a.status],
  })),
)

// ダイアログ
const dialog = ref(false)
const editing = ref<Appointment | null>(null)
const defaults = ref<{ start_at?: string; end_at?: string }>({})

function openNew(start?: string, end?: string) {
  editing.value = null
  defaults.value = { start_at: start, end_at: end }
  dialog.value = true
}

const WEEKDAY_INDEX: Record<string, number> = { sun: 0, mon: 1, tue: 2, wed: 3, thu: 4, fri: 5, sat: 6 }

const options = computed<CalendarOptions>(() => {
  const s = settings.value
  const openDays = [0, 1, 2, 3, 4, 5, 6].filter(
    (d) => !(s?.closed_weekdays ?? []).some((w) => WEEKDAY_INDEX[w] === d),
  )
  return {
    plugins: [classicTheme, timeGridPlugin, dayGridPlugin, interactionPlugin],
    locale: jaLocale,
    timeZone: 'Asia/Tokyo',
    initialView: 'timeGridWeek',
    headerToolbar: {
      start: 'prev,next today',
      center: 'title',
      end: 'timeGridDay,timeGridWeek,dayGridMonth',
    },
    height: 'auto',
    allDaySlot: false,
    nowIndicator: true,
    slotMinTime: s?.business_start_time ?? '09:00',
    slotMaxTime: s?.business_end_time ?? '20:00',
    slotDuration: `00:${String(Math.min(s?.appointment_interval_minutes ?? 30, 59)).padStart(2, '0')}:00`,
    businessHours: {
      daysOfWeek: openDays,
      startTime: s?.business_start_time ?? '09:00',
      endTime: s?.business_end_time ?? '20:00',
    },
    selectable: true,
    editable: true,
    events: events.value,
    datesSet: (info: DatesSetInfo) => {
      range.value = { start: info.start.toISOString(), end: info.end.toISOString() }
      load()
    },
    select: (info: DateSelectInfo) => openNew(info.start.toISOString(), info.end.toISOString()),
    eventClick: (info: EventClickInfo) => {
      editing.value = appointments.value.find((a) => String(a.id) === info.event.id) ?? null
      dialog.value = true
    },
    // ドラッグ移動・リサイズで時間変更
    eventChange: async (info: EventChangeInfo) => {
      const { error } = await api.PATCH('/api/appointments/{appt_id}', {
        params: { path: { appt_id: Number(info.event.id) } },
        body: { start_at: info.event.start!.toISOString(), end_at: info.event.end!.toISOString() },
      })
      if (error) {
        info.revert()
        snackbar.value = errorMessage(error)
      }
      await load()
    },
  }
})

const staffItems = computed(() => [
  { value: null, title: 'すべての担当者' },
  ...(staff.value ?? []).map((s) => ({ value: s.id, title: s.full_name })),
])
</script>

<template>
  <div>
    <PageHeader title="予約カレンダー" subtitle="空き枠をドラッグして予約を登録・予約をドラッグして時間を変更">
      <v-select
        v-model="staffFilter"
        :items="staffItems"
        density="compact"
        hide-details
        style="max-width: 220px"
      />
      <v-btn color="primary" prepend-icon="mdi-plus" @click="openNew()">予約を登録</v-btn>
    </PageHeader>

    <div class="d-flex flex-wrap ga-2 mb-3">
      <v-chip
        v-for="(label, key) in STATUS_LABELS"
        :key="key"
        size="small"
        :color="STATUS_COLORS[key]"
        variant="flat"
      >
        {{ label }}
      </v-chip>
    </div>

    <v-card class="pa-3">
      <FullCalendar :options="options" />
    </v-card>

    <AppointmentDialog
      v-model="dialog"
      :appointment="editing"
      :defaults="defaults"
      @saved="load"
    />
    <v-snackbar :model-value="!!snackbar" color="error" @update:model-value="snackbar = null">
      {{ snackbar }}
    </v-snackbar>
  </div>
</template>
