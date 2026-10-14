<script setup lang="ts">
/** 患者さんに説明・署名してもらう施術計画の内容（署名時のスナップショットにも使う） */
type PlanContent = {
  title?: string
  chief_complaint?: string
  start_date?: string | null
  next_visit_date?: string | null
  visit_guide_type?: string | null
  visit_guide_count?: number | null
  visit_guide_note?: string
  expected_recovery_weeks_min?: number | null
  expected_recovery_weeks_max?: number | null
  rebound_reaction_note?: string
  [key: string]: unknown
}
const props = defineProps<{ plan: PlanContent }>()

const recovery = computed(() => {
  const { expected_recovery_weeks_min: lo, expected_recovery_weeks_max: hi } = props.plan
  if (lo != null && hi != null) return lo === hi ? `約${lo}週間` : `約${lo}〜${hi}週間`
  if (lo != null) return `${lo}週間〜`
  if (hi != null) return `〜${hi}週間`
  return ''
})
const instructions = computed(() =>
  PLAN_INSTRUCTIONS.map((f) => ({ ...f, value: String(props.plan[f.key] ?? '') })).filter(
    (f) => f.value,
  ),
)
</script>

<template>
  <v-table density="comfortable">
    <tbody>
      <tr v-if="plan.title"><th style="width: 180px">計画</th><td>{{ plan.title }}</td></tr>
      <tr v-if="plan.chief_complaint"><th>お悩み（主訴）</th><td>{{ plan.chief_complaint }}</td></tr>
      <tr v-if="plan.start_date"><th>開始日</th><td>{{ plan.start_date }}</td></tr>
      <tr v-if="visitGuideText(plan)"><th>通院の目安</th><td>{{ visitGuideText(plan) }}</td></tr>
      <tr v-if="plan.next_visit_date"><th>次回来院日</th><td>{{ plan.next_visit_date }}</td></tr>
      <tr v-if="recovery"><th>改善の目安</th><td>{{ recovery }}</td></tr>
      <tr v-for="f in instructions" :key="f.key">
        <th>{{ f.label }}</th>
        <td style="white-space: pre-wrap">{{ f.value }}</td>
      </tr>
      <tr v-if="plan.rebound_reaction_note">
        <th>好転反応について</th>
        <td style="white-space: pre-wrap">{{ plan.rebound_reaction_note }}</td>
      </tr>
    </tbody>
  </v-table>
</template>
