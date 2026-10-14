<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

type Brief = Schemas['PatientBrief']

const model = defineModel<number | null>({ default: null })
const props = defineProps<{ initial?: Brief | null }>()

const search = ref('')
const items = ref<Brief[]>(props.initial ? [props.initial] : [])
const loading = ref(false)

let timer: ReturnType<typeof setTimeout> | undefined
watch(search, (q) => {
  clearTimeout(timer)
  if (!q) return
  timer = setTimeout(async () => {
    loading.value = true
    const { data } = await useApi().GET('/api/patients', { params: { query: { q, limit: 20 } } })
    const selected = items.value.find((i) => i.id === model.value)
    items.value = [...(selected ? [selected] : []), ...(data?.items ?? [])].filter(
      (v, i, arr) => arr.findIndex((x) => x.id === v.id) === i,
    )
    loading.value = false
  }, 250)
})

const label = (p: Brief) => `${p.card_no}  ${p.last_name} ${p.first_name}（${p.last_name_kana} ${p.first_name_kana}）`
</script>

<template>
  <v-autocomplete
    v-model="model"
    v-model:search="search"
    :items="items"
    :item-title="label"
    item-value="id"
    :loading="loading"
    label="患者"
    placeholder="氏名・フリガナ・診察券番号で検索"
    no-filter
    clearable
    no-data-text="該当する患者がいません"
  />
</template>
