<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

const api = useApi()
const { isAdmin } = useAuth()
if (!isAdmin.value) await navigateTo('/')

const tab = ref('clinic')
const snackbar = ref<{ text: string; color: string } | null>(null)
const notify = (text: string, color = 'success') => (snackbar.value = { text, color })

// --- 院設定 ---
const { data: settings } = await useAsyncData('clinic-settings', async () => {
  const { data } = await api.GET('/api/clinic/settings')
  return data ?? null
})
const hhmm = (t: string | null | undefined) => (t ? t.slice(0, 5) : null)
const sform = reactive({
  display_name: '',
  phone: '',
  address: '',
  booking_description: '',
  business_start_time: '09:00',
  business_end_time: '20:00',
  break_start_time: null as string | null,
  break_end_time: null as string | null,
  appointment_interval_minutes: 30 as Schemas['ClinicSettingsUpdate']['appointment_interval_minutes'],
  closed_weekdays: [] as Schemas['ClinicSettingsUpdate']['closed_weekdays'],
  primary_color: '#1D4ED8',
})
watchEffect(() => {
  const s = settings.value
  if (!s) return
  Object.assign(sform, {
    ...s,
    business_start_time: hhmm(s.business_start_time),
    business_end_time: hhmm(s.business_end_time),
    break_start_time: hhmm(s.break_start_time),
    break_end_time: hhmm(s.break_end_time),
  })
})
const WEEKDAYS = [
  { value: 'mon', title: '月' },
  { value: 'tue', title: '火' },
  { value: 'wed', title: '水' },
  { value: 'thu', title: '木' },
  { value: 'fri', title: '金' },
  { value: 'sat', title: '土' },
  { value: 'sun', title: '日' },
]
async function saveSettings() {
  const { data, error } = await api.PUT('/api/clinic/settings', {
    body: {
      ...sform,
      break_start_time: sform.break_start_time || null,
      break_end_time: sform.break_end_time || null,
    },
  })
  if (error) return notify(errorMessage(error), 'error')
  settings.value = data ?? null
  notify('院の設定を保存しました')
}

// --- 施術メニュー ---
const { data: menus, refresh: refreshMenus } = await useAsyncData('menus-all', async () => {
  const { data } = await api.GET('/api/treatment-menus')
  return data ?? []
})
const menuDialog = ref(false)
const menuEditingId = ref<number | null>(null)
const emptyMenu = (): Schemas['TreatmentMenuCreate'] => ({
  name: '',
  description: '',
  price: 0,
  duration_minutes: 30,
  is_active: true,
  display_order: 0,
})
const mform = reactive(emptyMenu())
function openMenu(m: Schemas['TreatmentMenuOut'] | null) {
  menuEditingId.value = m?.id ?? null
  Object.assign(mform, m ?? emptyMenu())
  menuDialog.value = true
}
async function saveMenu() {
  const body = { ...mform, price: Number(mform.price), duration_minutes: Number(mform.duration_minutes) }
  const { error } = menuEditingId.value
    ? await api.PUT('/api/treatment-menus/{menu_id}', {
        params: { path: { menu_id: menuEditingId.value } },
        body,
      })
    : await api.POST('/api/treatment-menus', { body })
  if (error) return notify(errorMessage(error), 'error')
  menuDialog.value = false
  await refreshMenus()
}
async function deleteMenu(id: number) {
  if (!confirm('このメニューを削除しますか？（使わなくなった場合は「無効」にする方法もあります）')) return
  await api.DELETE('/api/treatment-menus/{menu_id}', { params: { path: { menu_id: id } } })
  await refreshMenus()
}

// --- スタッフ ---
const { data: staff, refresh: refreshStaff } = await useAsyncData('staff', async () => {
  const { data } = await api.GET('/api/staff')
  return data ?? []
})
const staffDialog = ref(false)
const stform = reactive<Schemas['StaffCreate']>({
  username: '',
  full_name: '',
  role: 'practitioner',
  password: '',
})
async function createStaff() {
  const { error } = await api.POST('/api/staff', { body: stform })
  if (error) return notify(errorMessage(error), 'error')
  staffDialog.value = false
  Object.assign(stform, { username: '', full_name: '', role: 'practitioner', password: '' })
  await refreshStaff()
}
</script>

<template>
  <div>
    <PageHeader title="院の設定" />
    <v-card>
      <v-tabs v-model="tab" color="primary">
        <v-tab value="clinic">基本設定</v-tab>
        <v-tab value="menus">施術メニュー</v-tab>
        <v-tab value="staff">スタッフ</v-tab>
      </v-tabs>
      <v-divider />

      <v-tabs-window v-model="tab">
        <v-tabs-window-item value="clinic">
          <v-card-text>
            <v-row density="compact">
              <v-col cols="12" md="6"><v-text-field v-model="sform.display_name" label="表示用院名" /></v-col>
              <v-col cols="12" md="6"><v-text-field v-model="sform.phone" label="電話番号" /></v-col>
              <v-col cols="12"><v-text-field v-model="sform.address" label="住所" /></v-col>
              <v-col cols="6" md="3">
                <v-text-field v-model="sform.business_start_time" type="time" label="営業開始" />
              </v-col>
              <v-col cols="6" md="3">
                <v-text-field v-model="sform.business_end_time" type="time" label="営業終了" />
              </v-col>
              <v-col cols="6" md="3">
                <v-text-field v-model="sform.break_start_time" type="time" label="休憩開始" clearable />
              </v-col>
              <v-col cols="6" md="3">
                <v-text-field v-model="sform.break_end_time" type="time" label="休憩終了" clearable />
              </v-col>
              <v-col cols="12" md="4">
                <v-select
                  v-model="sform.appointment_interval_minutes"
                  :items="[5, 10, 15, 20, 30, 60].map((v) => ({ value: v, title: `${v}分` }))"
                  label="予約受付単位"
                />
              </v-col>
              <v-col cols="12" md="8">
                <div class="text-caption text-medium-emphasis">休診曜日</div>
                <v-chip-group v-model="sform.closed_weekdays" multiple selected-class="text-error">
                  <v-chip v-for="w in WEEKDAYS" :key="w.value" :value="w.value" filter variant="outlined">
                    {{ w.title }}
                  </v-chip>
                </v-chip-group>
              </v-col>
              <v-col cols="12">
                <v-textarea v-model="sform.booking_description" label="予約画面に表示する説明文" rows="2" auto-grow />
              </v-col>
            </v-row>
            <div class="d-flex justify-end">
              <v-btn color="primary" @click="saveSettings">保存</v-btn>
            </div>
          </v-card-text>
        </v-tabs-window-item>

        <v-tabs-window-item value="menus">
          <v-card-text class="d-flex justify-end">
            <v-btn color="primary" prepend-icon="mdi-plus" @click="openMenu(null)">メニューを追加</v-btn>
          </v-card-text>
          <v-table hover>
            <thead>
              <tr><th>並び順</th><th>メニュー名</th><th>所要時間</th><th>料金</th><th>状態</th><th /></tr>
            </thead>
            <tbody>
              <tr v-for="m in menus" :key="m.id">
                <td>{{ m.display_order }}</td>
                <td>{{ m.name }}</td>
                <td>{{ m.duration_minutes }}分</td>
                <td>{{ m.price.toLocaleString() }}円</td>
                <td>
                  <v-chip size="small" :color="m.is_active ? 'success' : undefined">
                    {{ m.is_active ? '有効' : '無効' }}
                  </v-chip>
                </td>
                <td class="text-right">
                  <v-btn icon="mdi-pencil" variant="text" size="small" @click="openMenu(m)" />
                  <v-btn icon="mdi-delete" variant="text" size="small" @click="deleteMenu(m.id)" />
                </td>
              </tr>
            </tbody>
          </v-table>
        </v-tabs-window-item>

        <v-tabs-window-item value="staff">
          <v-card-text class="d-flex justify-end">
            <v-btn color="primary" prepend-icon="mdi-account-plus" @click="staffDialog = true">
              スタッフを追加
            </v-btn>
          </v-card-text>
          <v-table>
            <thead><tr><th>氏名</th><th>ユーザー名</th><th>役割</th></tr></thead>
            <tbody>
              <tr v-for="s in staff" :key="s.id">
                <td>{{ s.full_name }}</td>
                <td>{{ s.username }}</td>
                <td>{{ ROLE_LABELS[s.role] }}</td>
              </tr>
            </tbody>
          </v-table>
        </v-tabs-window-item>
      </v-tabs-window>
    </v-card>

    <v-dialog v-model="menuDialog" max-width="560">
      <v-card :title="menuEditingId ? 'メニューの編集' : 'メニューの追加'">
        <v-card-text>
          <v-text-field v-model="mform.name" label="メニュー名" />
          <v-row density="compact">
            <v-col cols="6"><v-text-field v-model.number="mform.duration_minutes" type="number" step="5" label="所要時間（分）" /></v-col>
            <v-col cols="6"><v-text-field v-model.number="mform.price" type="number" label="料金（円）" /></v-col>
            <v-col cols="6"><v-text-field v-model.number="mform.display_order" type="number" label="並び順" /></v-col>
            <v-col cols="6"><v-switch v-model="mform.is_active" label="有効" color="primary" /></v-col>
          </v-row>
          <v-textarea v-model="mform.description" label="説明" rows="2" auto-grow />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="menuDialog = false">キャンセル</v-btn>
          <v-btn color="primary" @click="saveMenu">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-dialog v-model="staffDialog" max-width="480">
      <v-card title="スタッフの追加">
        <v-card-text>
          <v-text-field v-model="stform.full_name" label="氏名" />
          <v-text-field v-model="stform.username" label="ユーザー名（ログインID）" />
          <v-select v-model="stform.role" :items="toItems(ROLE_LABELS)" label="役割" />
          <v-text-field v-model="stform.password" type="password" label="初期パスワード（8文字以上）" />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="staffDialog = false">キャンセル</v-btn>
          <v-btn color="primary" @click="createStaff">追加</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar :model-value="!!snackbar" :color="snackbar?.color" @update:model-value="snackbar = null">
      {{ snackbar?.text }}
    </v-snackbar>
  </div>
</template>
