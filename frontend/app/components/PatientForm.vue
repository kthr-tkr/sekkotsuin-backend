<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

type PatientInput = Schemas['PatientCreate']

const props = defineProps<{ initial?: Partial<PatientInput>; submitLabel?: string }>()
const emit = defineEmits<{ submit: [value: PatientInput] }>()

const form = reactive<PatientInput>({
  last_name: '',
  first_name: '',
  last_name_kana: '',
  first_name_kana: '',
  birth_date: '',
  phone: '',
  email: null,
  address: '',
  notes: '',
  ...props.initial,
})

const required = (v: string) => !!v || '必須項目です'
const kana = (v: string) => /^[ァ-ヶーぁ-ゖ\s　]+$/.test(v) || 'カタカナで入力してください'

async function onSubmit(e: Promise<{ valid: boolean }>) {
  if (!(await e).valid) return
  emit('submit', { ...form, email: form.email || null })
}
</script>

<template>
  <v-form @submit.prevent="onSubmit">
    <v-row density="compact">
      <v-col cols="6" md="3">
        <v-text-field v-model="form.last_name" label="姓" :rules="[required]" />
      </v-col>
      <v-col cols="6" md="3">
        <v-text-field v-model="form.first_name" label="名" :rules="[required]" />
      </v-col>
      <v-col cols="6" md="3">
        <v-text-field v-model="form.last_name_kana" label="セイ" :rules="[required, kana]" />
      </v-col>
      <v-col cols="6" md="3">
        <v-text-field v-model="form.first_name_kana" label="メイ" :rules="[required, kana]" />
      </v-col>
      <v-col cols="12" md="4">
        <v-text-field v-model="form.birth_date" label="生年月日" type="date" :rules="[required]" />
      </v-col>
      <v-col cols="12" md="4">
        <v-text-field v-model="form.phone" label="電話番号" type="tel" :rules="[required]" />
      </v-col>
      <v-col cols="12" md="4">
        <v-text-field v-model="form.email" label="メールアドレス（任意）" type="email" />
      </v-col>
      <v-col cols="12">
        <v-text-field v-model="form.address" label="住所（任意）" />
      </v-col>
      <v-col cols="12">
        <v-textarea v-model="form.notes" label="メモ（任意）" rows="3" auto-grow />
      </v-col>
    </v-row>
    <div class="d-flex justify-end">
      <slot name="actions" />
      <v-btn type="submit" color="primary">{{ submitLabel ?? '保存' }}</v-btn>
    </div>
  </v-form>
</template>
