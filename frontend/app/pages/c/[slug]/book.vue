<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

definePageMeta({ layout: 'portal', public: true })

const { slug, me, fetchMe } = usePortal()
const api = useApi()
const { data } = await usePortalClinic(slug.value)
const clinic = computed(() => data.value?.clinic)

onMounted(async () => {
  if (!(await fetchMe())) await navigateTo(`/c/${slug.value}/login?next=/c/${slug.value}/book`)
})

const step = ref(1)
const menuId = ref<number | null>(null)
const day = ref<string>('')
const slot = ref<Schemas['PortalSlot'] | null>(null)
const notes = ref('')
const error = ref<string | null>(null)
const booking = ref(false)
const done = ref<Schemas['MyAppointment'] | null>(null)

const menu = computed(() => clinic.value?.menus.find((m) => m.id === menuId.value))

// 予約できる日の候補（休診日を除く、受付期間内）
const WEEKDAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat']
const days = computed(() => {
  const c = clinic.value
  if (!c) return []
  const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Tokyo' }).format(new Date())
  const out: string[] = []
  for (let i = 0; i <= c.booking_window_days && out.length < 21; i++) {
    const d = new Date(`${today}T12:00:00Z`)
    d.setUTCDate(d.getUTCDate() + i)
    const iso = d.toISOString().slice(0, 10)
    if (!c.closed_weekdays.includes(WEEKDAYS[d.getUTCDay()]!)) out.push(iso)
  }
  return out
})

const { data: slots, pending: loadingSlots } = await useAsyncData(
  'portal-slots',
  async () => {
    if (!menuId.value || !day.value) return []
    const { data } = await api.GET('/api/portal/{slug}/availability', {
      params: { path: { slug: slug.value }, query: { date: day.value, menu_id: menuId.value } },
    })
    return data ?? []
  },
  { watch: [menuId, day] },
)
const openSlots = computed(() => (slots.value ?? []).filter((s) => s.available))

function pickMenu(id: number) {
  menuId.value = id
  slot.value = null
  step.value = 2
}
function pickSlot(s: Schemas['PortalSlot']) {
  slot.value = s
  step.value = 3
}

async function book() {
  if (!menuId.value || !slot.value) return
  booking.value = true
  error.value = null
  const { data: res, error: err } = await api.POST('/api/me/appointments', {
    body: { treatment_menu_id: menuId.value, start_at: slot.value.start_at, notes: notes.value },
  })
  booking.value = false
  if (err || !res) {
    error.value = errorMessage(err, '予約できませんでした。')
    return
  }
  done.value = res
  step.value = 4
}

const dayLabel = (iso: string) => `${Number(iso.slice(5, 7))}/${Number(iso.slice(8))}（${weekdayJa(iso)}）`
</script>

<template>
  <div v-if="clinic && me">
    <h1 class="text-headline-small font-weight-bold mb-4">Web 予約</h1>

    <v-card v-if="step === 4 && done" class="pa-4 text-center">
      <v-icon icon="mdi-check-circle" color="success" size="56" />
      <v-card-title>ご予約を受け付けました</v-card-title>
      <v-card-text>
        <p class="text-title-medium mb-1">{{ formatDateTime(done.start_at) }}</p>
        <p class="mb-4">{{ done.menu_name }}</p>
        <v-alert type="info" variant="tonal" class="text-left mb-4">
          ご来院前に Web 問診にご回答ください。回答いただくと予約が確定します。
        </v-alert>
        <v-btn v-if="done.intake_token" color="primary" size="large" block :to="`/q/${done.intake_token}`" class="mb-2">
          Web 問診に回答する
        </v-btn>
        <v-btn variant="text" block :to="`/c/${slug}/mypage`">マイページへ</v-btn>
      </v-card-text>
    </v-card>

    <template v-else>
      <v-card class="mb-4" :title="`1. メニューを選ぶ${menu ? `：${menu.name}` : ''}`">
        <v-list v-if="step === 1" lines="two">
          <v-list-item v-for="m in clinic.menus" :key="m.id" :title="m.name" @click="pickMenu(m.id)">
            <v-list-item-subtitle>{{ m.duration_minutes }}分 ・ {{ yen(m.price) }}</v-list-item-subtitle>
            <template #append><v-icon icon="mdi-chevron-right" /></template>
          </v-list-item>
        </v-list>
        <v-card-actions v-else>
          <v-btn variant="text" @click="step = 1">変更</v-btn>
        </v-card-actions>
      </v-card>

      <v-card v-if="step >= 2" class="mb-4" :title="`2. 日時を選ぶ${slot ? `：${formatDateTime(slot.start_at)}` : ''}`">
        <v-card-text v-if="step === 2">
          <v-chip-group v-model="day" selected-class="bg-primary" mandatory="force" column>
            <v-chip v-for="d in days" :key="d" :value="d" variant="outlined">{{ dayLabel(d) }}</v-chip>
          </v-chip-group>
          <div v-if="day" class="mt-4">
            <v-progress-linear v-if="loadingSlots" indeterminate />
            <p v-else-if="!openSlots.length" class="text-medium-emphasis">この日は空きがありません。別の日をお選びください。</p>
            <div v-else class="slot-grid">
              <v-btn v-for="s in openSlots" :key="s.start_at" variant="outlined" color="primary" @click="pickSlot(s)">
                {{ formatTime(s.start_at) }}
              </v-btn>
            </div>
          </div>
          <p v-else class="text-medium-emphasis mt-2">日付を選ぶと、空いている時間が表示されます。</p>
        </v-card-text>
        <v-card-actions v-else>
          <v-btn variant="text" @click="step = 2">変更</v-btn>
        </v-card-actions>
      </v-card>

      <v-card v-if="step === 3 && slot && menu" title="3. 内容の確認">
        <v-card-text>
          <v-table density="compact" class="mb-4">
            <tbody>
              <tr><th style="width: 120px">お名前</th><td>{{ me.last_name }} {{ me.first_name }} 様</td></tr>
              <tr><th>日時</th><td>{{ formatDateTime(slot.start_at) }}〜{{ formatTime(slot.end_at) }}</td></tr>
              <tr><th>メニュー</th><td>{{ menu.name }}（{{ yen(menu.price) }}）</td></tr>
            </tbody>
          </v-table>
          <v-textarea v-model="notes" label="ご要望など（任意）" rows="2" auto-grow counter="500" />
          <p class="text-body-small text-medium-emphasis mb-3">
            キャンセルは予約の {{ clinic.cancel_deadline_hours }} 時間前までマイページからできます。
          </p>
          <v-alert v-if="error" type="error" variant="tonal" class="mb-3" :text="error" />
          <v-btn color="primary" size="x-large" block :loading="booking" @click="book">この内容で予約する</v-btn>
        </v-card-text>
      </v-card>
    </template>
  </div>
</template>

<style scoped>
.slot-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(88px, 1fr));
  gap: 8px;
}
</style>
