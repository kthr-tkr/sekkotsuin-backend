<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

definePageMeta({ layout: 'portal', public: true })

const { slug, me, fetchMe } = usePortal()
const api = useApi()
const snackbar = ref<{ text: string; color: string } | null>(null)

const appointments = ref<Schemas['MyAppointment'][]>([])
async function load() {
  const { data } = await api.GET('/api/me/appointments')
  appointments.value = data ?? []
}
onMounted(async () => {
  if (!(await fetchMe())) return navigateTo(`/c/${slug.value}/login?next=/c/${slug.value}/mypage`)
  await load()
})

const now = () => Date.now()
const upcoming = computed(() =>
  appointments.value
    .filter((a) => new Date(a.end_at).getTime() > now() && !['cancelled', 'no_show'].includes(a.status))
    .sort((a, b) => a.start_at.localeCompare(b.start_at)),
)
const history = computed(() => appointments.value.filter((a) => !upcoming.value.includes(a)))

const PATIENT_STATUS: Record<string, string> = {
  pending: '問診の回答待ち',
  booked: '予約確定',
  arrived: '来院',
  completed: 'ご来院済み',
  cancelled: 'キャンセル',
  no_show: 'キャンセル',
}

async function cancel(a: Schemas['MyAppointment']) {
  if (!confirm(`${formatDateTime(a.start_at)} の予約をキャンセルしますか？`)) return
  const { error } = await api.POST('/api/me/appointments/{appointment_id}/cancel', {
    params: { path: { appointment_id: a.id } },
  })
  if (error) snackbar.value = { text: errorMessage(error), color: 'error' }
  else snackbar.value = { text: '予約をキャンセルしました', color: 'success' }
  await load()
}

// プロフィール
const profileDialog = ref(false)
const pform = reactive({ phone: '', address: '', reminders_enabled: true })
function openProfile() {
  Object.assign(pform, {
    phone: me.value?.phone ?? '',
    address: me.value?.address ?? '',
    reminders_enabled: me.value?.reminders_enabled ?? true,
  })
  profileDialog.value = true
}
async function saveProfile() {
  const { data, error } = await api.PUT('/api/me', { body: pform })
  if (error || !data) return (snackbar.value = { text: errorMessage(error), color: 'error' })
  me.value = data
  profileDialog.value = false
  snackbar.value = { text: '登録情報を更新しました', color: 'success' }
}
</script>

<template>
  <div v-if="me">
    <div class="d-flex align-center mb-4">
      <div class="flex-grow-1">
        <h1 class="text-headline-small font-weight-bold">{{ me.last_name }} {{ me.first_name }} 様</h1>
        <div class="text-body-medium text-medium-emphasis">診察券番号 {{ me.card_no }}</div>
      </div>
      <v-btn variant="text" prepend-icon="mdi-account-edit-outline" @click="openProfile">登録情報</v-btn>
    </div>

    <v-btn color="primary" size="large" block prepend-icon="mdi-calendar-plus" class="mb-4" :to="`/c/${slug}/book`">
      新しく予約する
    </v-btn>

    <v-card title="今後のご予約" class="mb-4">
      <v-card-text v-if="!upcoming.length" class="text-medium-emphasis">ご予約はありません。</v-card-text>
      <v-card v-for="a in upcoming" :key="a.id" variant="outlined" class="ma-3">
        <v-card-item>
          <v-card-title class="text-title-medium">{{ formatDateTime(a.start_at) }}</v-card-title>
          <v-card-subtitle>{{ a.menu_name }}</v-card-subtitle>
          <template #append>
            <v-chip size="small" :color="a.status === 'pending' ? 'warning' : 'success'" variant="tonal">
              {{ PATIENT_STATUS[a.status] }}
            </v-chip>
          </template>
        </v-card-item>
        <v-card-actions>
          <v-btn v-if="a.intake_token" color="primary" variant="flat" :to="`/q/${a.intake_token}`">
            Web 問診に回答する
          </v-btn>
          <v-spacer />
          <v-btn v-if="a.can_cancel" color="error" variant="text" @click="cancel(a)">キャンセル</v-btn>
          <span v-else class="text-body-small text-medium-emphasis px-2">変更・キャンセルはお電話で</span>
        </v-card-actions>
      </v-card>
    </v-card>

    <v-card title="これまでのご予約">
      <v-list density="compact">
        <v-list-item v-if="!history.length" subtitle="まだありません" />
        <v-list-item
          v-for="a in history"
          :key="a.id"
          :title="formatDateTime(a.start_at)"
          :subtitle="`${a.menu_name} ・ ${PATIENT_STATUS[a.status]}`"
        />
      </v-list>
    </v-card>

    <v-dialog v-model="profileDialog" max-width="480">
      <v-card title="登録情報">
        <v-card-text>
          <p class="text-body-medium mb-3">お名前・生年月日の変更は院にお申し出ください。</p>
          <v-text-field :model-value="me.email" label="メールアドレス" readonly />
          <v-text-field v-model="pform.phone" type="tel" label="電話番号" />
          <v-text-field v-model="pform.address" label="住所" />
          <v-switch
            v-model="pform.reminders_enabled"
            label="予約の前日にお知らせ（リマインド）を受け取る"
            color="primary"
            hide-details
          />
        </v-card-text>
        <v-card-actions>
          <v-spacer />
          <v-btn variant="text" @click="profileDialog = false">閉じる</v-btn>
          <v-btn color="primary" @click="saveProfile">保存</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>

    <v-snackbar :model-value="!!snackbar" :color="snackbar?.color" @update:model-value="snackbar = null">
      {{ snackbar?.text }}
    </v-snackbar>
  </div>
</template>
