<script setup lang="ts">
/** 問診 URL の表示・コピーと、患者へのメール / SMS 送信 */
const props = defineProps<{ intake: { id: number; access_token: string } | null }>()
const emit = defineEmits<{ close: [] }>()

const url = computed(() => (props.intake ? `${window.location.origin}/q/${props.intake.access_token}` : ''))
const copied = ref(false)
const sending = ref<string | null>(null)
const result = ref<{ text: string; type: 'success' | 'error' } | null>(null)

watch(
  () => props.intake,
  () => (result.value = null),
)

async function copy() {
  await navigator.clipboard.writeText(url.value)
  copied.value = true
  setTimeout(() => (copied.value = false), 2000)
}

async function send(channel: 'email' | 'sms') {
  if (!props.intake) return
  sending.value = channel
  const { data, error } = await useApi().POST('/api/intakes/{intake_id}/send', {
    params: { path: { intake_id: props.intake.id } },
    body: { channels: [channel] },
  })
  sending.value = null
  result.value = error
    ? { text: errorMessage(error), type: 'error' }
    : { text: `${data!.map((n) => n.to).join('、')} に送信します`, type: 'success' }
}
</script>

<template>
  <v-dialog :model-value="!!intake" max-width="560" @update:model-value="emit('close')">
    <v-card title="問診URL">
      <v-card-text>
        <p class="mb-3 text-body-medium">
          このURLを患者さんに送ってください。回答されると問診一覧に表示されます。
        </p>
        <v-text-field :model-value="url" readonly hide-details class="mb-3">
          <template #append-inner>
            <v-btn
              :icon="copied ? 'mdi-check' : 'mdi-content-copy'"
              variant="text"
              size="small"
              aria-label="URL をコピー"
              @click="copy"
            />
          </template>
        </v-text-field>
        <div class="d-flex ga-2">
          <v-btn variant="tonal" prepend-icon="mdi-email-outline" :loading="sending === 'email'" @click="send('email')">
            メールで送る
          </v-btn>
          <v-btn variant="tonal" prepend-icon="mdi-message-text-outline" :loading="sending === 'sms'" @click="send('sms')">
            SMSで送る
          </v-btn>
        </div>
        <v-alert v-if="result" :type="result.type" variant="tonal" density="compact" class="mt-3" :text="result.text" />
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn :href="url" target="_blank" variant="text">開く</v-btn>
        <v-btn color="primary" @click="emit('close')">閉じる</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
