<script setup lang="ts">
definePageMeta({ layout: 'portal', public: true })

const { slug, me, fetchMe } = usePortal()
const { data } = await usePortalClinic(slug.value)
const clinic = computed(() => data.value?.clinic)
onMounted(fetchMe)

const WEEKDAY_JA: Record<string, string> = { mon: '月', tue: '火', wed: '水', thu: '木', fri: '金', sat: '土', sun: '日' }
const hm = (t: string) => t.slice(0, 5)
</script>

<template>
  <div v-if="clinic">
    <h1 class="text-headline-small font-weight-bold mb-2">{{ clinic.name }}</h1>
    <p v-if="clinic.booking_description" class="mb-4" style="white-space: pre-wrap">{{ clinic.booking_description }}</p>

    <v-card class="mb-4">
      <v-card-text class="d-flex flex-column ga-3">
        <v-btn color="primary" size="x-large" block prepend-icon="mdi-calendar-check" :to="`/c/${slug}/book`">
          Web で予約する
        </v-btn>
        <template v-if="!me">
          <v-btn variant="tonal" block :to="`/c/${slug}/register`">はじめての方（登録）</v-btn>
          <v-btn variant="text" block :to="`/c/${slug}/login`">登録済みの方はログイン</v-btn>
        </template>
        <v-btn v-else variant="tonal" block :to="`/c/${slug}/mypage`">
          {{ me.last_name }} 様のマイページ
        </v-btn>
      </v-card-text>
    </v-card>

    <v-card title="施術メニュー" class="mb-4">
      <v-list lines="two">
        <v-list-item v-for="m in clinic.menus" :key="m.id" :title="m.name">
          <v-list-item-subtitle>
            {{ m.duration_minutes }}分 ・ {{ yen(m.price) }}<span v-if="m.description"> ・ {{ m.description }}</span>
          </v-list-item-subtitle>
        </v-list-item>
      </v-list>
    </v-card>

    <v-card title="院の情報">
      <v-list density="compact">
        <v-list-item prepend-icon="mdi-clock-outline" :title="`${hm(clinic.business_start_time)}〜${hm(clinic.business_end_time)}`" subtitle="受付時間" />
        <v-list-item
          v-if="clinic.closed_weekdays.length"
          prepend-icon="mdi-calendar-remove-outline"
          :title="`${clinic.closed_weekdays.map((w) => WEEKDAY_JA[w]).join('・')}曜日`"
          subtitle="休診日"
        />
        <v-list-item v-if="clinic.phone" prepend-icon="mdi-phone" :title="clinic.phone" subtitle="電話" :href="`tel:${clinic.phone}`" />
        <v-list-item v-if="clinic.address" prepend-icon="mdi-map-marker-outline" :title="clinic.address" subtitle="住所" />
      </v-list>
    </v-card>
  </div>
</template>
