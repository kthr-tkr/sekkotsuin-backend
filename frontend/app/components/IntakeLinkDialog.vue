<script setup lang="ts">
const props = defineProps<{ token: string | null }>()
const emit = defineEmits<{ close: [] }>()

const url = computed(() => (props.token ? `${window.location.origin}/q/${props.token}` : ''))
const copied = ref(false)

async function copy() {
  await navigator.clipboard.writeText(url.value)
  copied.value = true
  setTimeout(() => (copied.value = false), 2000)
}
</script>

<template>
  <v-dialog :model-value="!!token" max-width="560" @update:model-value="emit('close')">
    <v-card title="問診URL">
      <v-card-text>
        <p class="mb-3 text-body-medium">
          このURLを患者さんに送ってください（SMS・LINE・メールなど）。回答されると問診一覧に表示されます。
        </p>
        <v-text-field :model-value="url" readonly hide-details>
          <template #append-inner>
            <v-btn
              :icon="copied ? 'mdi-check' : 'mdi-content-copy'"
              variant="text"
              size="small"
              @click="copy"
            />
          </template>
        </v-text-field>
      </v-card-text>
      <v-card-actions>
        <v-spacer />
        <v-btn :href="url" target="_blank" variant="text">開く</v-btn>
        <v-btn color="primary" @click="emit('close')">閉じる</v-btn>
      </v-card-actions>
    </v-card>
  </v-dialog>
</template>
