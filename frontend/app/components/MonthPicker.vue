<script setup lang="ts">
const month = defineModel<string>({ required: true })
</script>

<template>
  <div class="d-flex align-center ga-1">
    <v-btn icon="mdi-chevron-left" variant="text" size="small" aria-label="前の月" @click="month = shiftMonth(month, -1)" />
    <span class="text-title-medium font-weight-bold" style="min-width: 96px; text-align: center">
      {{ month.replace('-', '年') }}月
    </span>
    <v-btn icon="mdi-chevron-right" variant="text" size="small" aria-label="次の月" @click="month = shiftMonth(month, 1)" />
    <v-btn variant="text" size="small" @click="month = currentMonth()">今月</v-btn>
  </div>
</template>
