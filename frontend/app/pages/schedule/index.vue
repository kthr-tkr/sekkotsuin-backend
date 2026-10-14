<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

type Shift = Schemas['ShiftOut']

const api = useApi()
const { user, isAdmin } = useAuth()
const tab = ref<'shifts' | 'leaves'>('shifts')
const month = ref(currentMonth())
const snackbar = ref<{ text: string; color: string } | null>(null)

const { data: staff } = await useAsyncData('staff', async () => {
  const { data } = await api.GET('/api/staff')
  return data ?? []
})
const { data: shifts, refresh: refreshShifts } = await useAsyncData(
  'shifts',
  async () => {
    const { data } = await api.GET('/api/shifts', { params: { query: { month: month.value } } })
    return data ?? []
  },
  { watch: [month] },
)
const { data: leaves, refresh: refreshLeaves } = await useAsyncData(
  'leaves',
  async () => {
    const { data } = await api.GET('/api/leaves', { params: { query: { month: month.value } } })
    return data ?? []
  },
  { watch: [month] },
)

const days = computed(() => daysInMonth(month.value))
const shiftMap = computed(() => {
  const m = new Map<string, Shift>()
  for (const s of shifts.value ?? []) m.set(`${s.staff_id}:${s.date}`, s)
  return m
})
const leaveOn = (staffId: number, day: string) =>
  (leaves.value ?? []).find(
    (l) => l.staff_id === staffId && l.status === 'approved' && l.start_date <= day && day <= l.end_date,
  )

const hm = (t?: string | null) => (t ? t.slice(0, 5) : '')
function cellText(staffId: number, day: string) {
  const lv = leaveOn(staffId, day)
  if (lv) return LEAVE_TYPE_LABELS[lv.leave_type]
  const s = shiftMap.value.get(`${staffId}:${day}`)
  if (!s) return ''
  if (s.status === 'off') return '休'
  return `${hm(s.start_time)}\n${hm(s.end_time)}`
}
function cellClass(staffId: number, day: string) {
  if (leaveOn(staffId, day)) return 'cell-leave'
  const s = shiftMap.value.get(`${staffId}:${day}`)
  if (!s) return ''
  return s.status === 'off' ? 'cell-off' : 'cell-work'
}

// シフト編集
const shiftDialog = ref(false)
const shiftTarget = ref<{ staffId: number; day: string } | null>(null)
const sform = reactive({ status: 'working', start_time: '09:00', end_time: '18:00', memo: '' })
function openShift(staffId: number, day: string) {
  if (!isAdmin.value) return
  const s = shiftMap.value.get(`${staffId}:${day}`)
  shiftTarget.value = { staffId, day }
  Object.assign(sform, {
    status: s?.status ?? 'working',
    start_time: hm(s?.start_time) || '09:00',
    end_time: hm(s?.end_time) || '18:00',
    memo: s?.memo ?? '',
  })
  shiftDialog.value = true
}
async function saveShift() {
  const t = shiftTarget.value!
  const { error } = await api.PUT('/api/shifts/{staff_id}/{day}', {
    params: { path: { staff_id: t.staffId, day: t.day } },
    body: {
      status: sform.status as Shift['status'],
      start_time: sform.status === 'off' ? null : sform.start_time,
      end_time: sform.status === 'off' ? null : sform.end_time,
      memo: sform.memo,
    },
  })
  if (error) return (snackbar.value = { text: errorMessage(error), color: 'error' })
  shiftDialog.value = false
  await refreshShifts()
}
async function clearShift() {
  const t = shiftTarget.value!
  await api.DELETE('/api/shifts/{staff_id}/{day}', { params: { path: { staff_id: t.staffId, day: t.day } } })
  shiftDialog.value = false
  await refreshShifts()
}

// 休暇
const leaveDialog = ref(false)
const lform = reactive({
  staff_id: null as number | null,
  leave_type: 'paid_leave',
  start_date: '',
  end_date: '',
  reason: '',
})
function openLeave() {
  const today = new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Tokyo' }).format(new Date())
  Object.assign(lform, { staff_id: null, leave_type: 'paid_leave', start_date: today, end_date: today, reason: '' })
  leaveDialog.value = true
}
async function saveLeave() {
  const { error } = await api.POST('/api/leaves', {
    body: {
      ...lform,
      staff_id: lform.staff_id ?? undefined,
      leave_type: lform.leave_type as Schemas['LeaveCreate']['leave_type'],
    },
  })
  if (error) return (snackbar.value = { text: errorMessage(error), color: 'error' })
  leaveDialog.value = false
  snackbar.value = { text: isAdmin.value ? '休暇を登録しました' : '休暇を申請しました', color: 'success' }
  await refreshLeaves()
}
async function decide(id: number, status: 'approved' | 'rejected') {
  const { error } = await api.POST('/api/leaves/{leave_id}/decide', {
    params: { path: { leave_id: id } },
    body: { status },
  })
  if (error) snackbar.value = { text: errorMessage(error), color: 'error' }
  await refreshLeaves()
}
async function cancelLeave(id: number) {
  if (!confirm('この休暇を取り消しますか？')) return
  await api.POST('/api/leaves/{leave_id}/cancel', { params: { path: { leave_id: id } } })
  await refreshLeaves()
}

const staffItems = computed(() => (staff.value ?? []).map((s) => ({ value: s.id, title: s.full_name })))
const isWeekend = (d: string) => ['土', '日'].includes(weekdayJa(d))
</script>

<template>
  <div>
    <PageHeader title="シフト・休暇" subtitle="シフトと承認済みの休暇は、予約の空き枠に反映されます">
      <MonthPicker v-model="month" />
      <v-btn color="primary" prepend-icon="mdi-calendar-remove-outline" @click="openLeave">
        {{ isAdmin ? '休暇を登録' : '休暇を申請' }}
      </v-btn>
    </PageHeader>

    <v-card>
      <v-tabs v-model="tab" color="primary">
        <v-tab value="shifts">シフト表</v-tab>
        <v-tab value="leaves">
          休暇
          <v-badge
            v-if="(leaves ?? []).some((l) => l.status === 'requested')"
            color="warning"
            dot
            inline
          />
        </v-tab>
      </v-tabs>
      <v-divider />

      <v-tabs-window v-model="tab">
        <v-tabs-window-item value="shifts">
          <div class="grid-wrap">
            <table class="shift-grid">
              <thead>
                <tr>
                  <th class="sticky">スタッフ</th>
                  <th v-for="d in days" :key="d" :class="{ weekend: isWeekend(d) }">
                    {{ Number(d.slice(8)) }}<br /><small>{{ weekdayJa(d) }}</small>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="s in staff" :key="s.id">
                  <th class="sticky">{{ s.full_name }}<br /><small>{{ ROLE_LABELS[s.role] }}</small></th>
                  <td
                    v-for="d in days"
                    :key="d"
                    :class="[cellClass(s.id, d), { editable: isAdmin }]"
                    :title="isAdmin ? 'クリックして編集' : undefined"
                    @click="openShift(s.id, d)"
                  >
                    {{ cellText(s.id, d) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="text-body-small text-medium-emphasis pa-3">
            空欄は営業時間どおりの勤務として扱います。{{ isAdmin ? 'セルをクリックするとシフトを編集できます。' : '' }}
          </p>
        </v-tabs-window-item>

        <v-tabs-window-item value="leaves">
          <v-table>
            <thead>
              <tr><th>スタッフ</th><th>種類</th><th>期間</th><th>理由</th><th>状態</th><th /></tr>
            </thead>
            <tbody>
              <tr v-if="!leaves?.length"><td colspan="6" class="text-medium-emphasis">この月の休暇はありません</td></tr>
              <tr v-for="l in leaves" :key="l.id">
                <td>{{ l.staff.full_name }}</td>
                <td>{{ LEAVE_TYPE_LABELS[l.leave_type] }}</td>
                <td>{{ l.start_date }}{{ l.end_date !== l.start_date ? ` 〜 ${l.end_date}` : '' }}</td>
                <td>{{ l.reason || '-' }}</td>
                <td>
                  <v-chip size="small" :color="LEAVE_STATUS_COLORS[l.status]" variant="flat">
                    {{ LEAVE_STATUS_LABELS[l.status] }}
                  </v-chip>
                </td>
                <td class="text-right">
                  <template v-if="isAdmin && l.status === 'requested'">
                    <v-btn size="small" color="success" variant="tonal" class="mr-1" @click="decide(l.id, 'approved')">承認</v-btn>
                    <v-btn size="small" color="error" variant="text" @click="decide(l.id, 'rejected')">却下</v-btn>
                  </template>
                  <v-btn
                    v-if="(isAdmin || l.staff_id === user?.id) && ['requested', 'approved'].includes(l.status)"
                    size="small"
                    variant="text"
                    @click="cancelLeave(l.id)"
                  >
                    取消
                  </v-btn>
                </td>
              </tr>
            </tbody>
          </v-table>
        </v-tabs-window-item>
      </v-tabs-window>
    </v-card>

    <v-dialog v-model="shiftDialog" max-width="420">
      <v-card :title="`シフト: ${shiftTarget?.day}`">
        <v-card-text>
          <v-select v-model="sform.status" :items="toItems(SHIFT_LABELS)" label="区分" />
          <v-row v-if="sform.status !== 'off'" density="compact">
            <v-col cols="6"><v-text-field v-model="sform.start_time" type="time" label="開始" /></v-col>
            <v-col cols="6"><v-text-field v-model="sform.end_time" type="time" label="終了" /></v-col>
          </v-row>
          <v-text-field v-model="sform.memo" label="メモ" />
        </v-card-text>
        <v-card-actions>
          <v-btn variant="text" color="error" @click="clearShift">未設定に戻す</v-btn>
          <v-spacer />
          <v-btn variant="text" @click="shiftDialog = false">閉じる</v-btn>
          <v-btn color="primary" @click="saveShift">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="leaveDialog" max-width="480">
      <v-card :title="isAdmin ? '休暇の登録' : '休暇の申請'">
        <v-card-text>
          <v-select
            v-if="isAdmin"
            v-model="lform.staff_id"
            :items="staffItems"
            label="スタッフ（空欄なら自分）"
            clearable
          />
          <v-select v-model="lform.leave_type" :items="toItems(LEAVE_TYPE_LABELS)" label="種類" />
          <v-row density="compact">
            <v-col cols="6"><v-text-field v-model="lform.start_date" type="date" label="開始日" /></v-col>
            <v-col cols="6"><v-text-field v-model="lform.end_date" type="date" label="終了日" /></v-col>
          </v-row>
          <v-text-field v-model="lform.reason" label="理由（任意）" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="leaveDialog = false">閉じる</v-btn>
          <v-btn color="primary" @click="saveLeave">{{ isAdmin ? '登録' : '申請' }}</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar :model-value="!!snackbar" :color="snackbar?.color" @update:model-value="snackbar = null">
      {{ snackbar?.text }}
    </v-snackbar>
  </div>
</template>

<style scoped>
.grid-wrap {
  overflow-x: auto;
}
.shift-grid {
  border-collapse: collapse;
  font-size: 12px;
  min-width: 100%;
}
.shift-grid th,
.shift-grid td {
  border: 1px solid rgb(0 0 0 / 0.08);
  padding: 4px;
  text-align: center;
  white-space: pre-line;
  min-width: 44px;
  height: 44px;
}
.shift-grid th.sticky {
  position: sticky;
  left: 0;
  background: rgb(var(--v-theme-surface));
  text-align: left;
  min-width: 120px;
  z-index: 1;
}
.shift-grid th.weekend {
  color: rgb(var(--v-theme-error));
}
.shift-grid td.editable {
  cursor: pointer;
}
.shift-grid td.editable:hover {
  outline: 2px solid rgb(var(--v-theme-primary));
  outline-offset: -2px;
}
.cell-work {
  background: rgb(29 78 216 / 0.08);
}
.cell-off {
  background: rgb(0 0 0 / 0.06);
  color: rgb(0 0 0 / 0.6);
}
.cell-leave {
  background: rgb(245 158 11 / 0.18);
}
</style>
