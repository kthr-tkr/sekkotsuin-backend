<script setup lang="ts">
/**
 * 1系列の縦棒グラフ（日別売上など）。
 * 棒は最大 24px、上端のみ 4px の角丸、ホバーでツールチップ。
 */
type Bar = { label: string; value: number; tooltip?: string }
const props = defineProps<{ bars: Bar[]; format?: (v: number) => string; label: string }>()

const W = 720
const H = 220
const M = { top: 12, right: 8, bottom: 24, left: 56 }
const iw = W - M.left - M.right
const ih = H - M.top - M.bottom
const fmt = (v: number) => (props.format ? props.format(v) : v.toLocaleString())

// 目盛りは 1・2・5 系の切りのいい値にする
const ticks = computed(() => {
  const max = Math.max(1, ...props.bars.map((b) => b.value))
  const raw = max / 4
  const p = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map((m) => m * p).find((s) => s >= raw)!
  const top = Math.ceil(max / step) * step
  return Array.from({ length: Math.round(top / step) + 1 }, (_, i) => i * step)
})
const yMax = computed(() => ticks.value[ticks.value.length - 1]!)
const band = computed(() => iw / Math.max(1, props.bars.length))
const barW = computed(() => Math.min(24, band.value * 0.7))
const x = (i: number) => M.left + band.value * i + band.value / 2
const y = (v: number) => M.top + ih - (v / yMax.value) * ih

function barPath(i: number, v: number) {
  const h = (v / yMax.value) * ih
  if (h <= 0) return ''
  const r = Math.min(4, h, barW.value / 2)
  const x0 = x(i) - barW.value / 2
  const x1 = x0 + barW.value
  const yb = M.top + ih
  const yt = yb - h
  return `M${x0},${yb} V${yt + r} Q${x0},${yt} ${x0 + r},${yt} H${x1 - r} Q${x1},${yt} ${x1},${yt + r} V${yb} Z`
}

const labelEvery = computed(() => Math.max(1, Math.ceil(props.bars.length / 10)))
const hover = ref<number | null>(null)
</script>

<template>
  <div class="viz-root">
    <svg :viewBox="`0 0 ${W} ${H}`" role="img" :aria-label="label" class="chart">
      <g>
        <template v-for="t in ticks" :key="t">
          <line :x1="M.left" :x2="W - M.right" :y1="y(t)" :y2="y(t)" class="grid" />
          <text :x="M.left - 6" :y="y(t)" class="axis" text-anchor="end" dominant-baseline="middle">
            {{ fmt(t) }}
          </text>
        </template>
        <template v-for="(b, i) in bars" :key="`l${i}`">
          <text v-if="i % labelEvery === 0" :x="x(i)" :y="H - 6" class="axis" text-anchor="middle">
            {{ b.label }}
          </text>
        </template>
      </g>
      <path
        v-for="(b, i) in bars"
        :key="`b${i}`"
        :d="barPath(i, b.value)"
        class="bar"
        :class="{ dim: hover !== null && hover !== i }"
      />
      <rect
        v-for="(b, i) in bars"
        :key="`h${i}`"
        :x="x(i) - band / 2"
        :y="M.top"
        :width="band"
        :height="ih"
        fill="transparent"
        @pointerenter="hover = i"
        @pointerleave="hover = null"
      />
    </svg>
    <div
      v-if="hover !== null"
      class="tooltip"
      :style="{ left: `${(x(hover) / W) * 100}%` }"
    >
      <div class="tt-title">{{ bars[hover]!.tooltip ?? bars[hover]!.label }}</div>
      <div class="tt-value">{{ fmt(bars[hover]!.value) }}</div>
    </div>
  </div>
</template>

<style scoped>
.viz-root {
  --surface-1: #fcfcfb;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --grid: #e6e5e1;
  --series-1: #2a78d6;
  position: relative;
  max-width: 900px;
}
.chart {
  width: 100%;
  height: auto;
  display: block;
}
.grid {
  stroke: var(--grid);
  stroke-width: 1;
}
.axis {
  font-size: 11px;
  fill: var(--text-secondary);
}
.bar {
  fill: var(--series-1);
  transition: opacity 0.1s;
}
.bar.dim {
  opacity: 0.45;
}
.tooltip {
  position: absolute;
  top: 0;
  transform: translateX(-50%);
  background: var(--surface-1);
  border: 1px solid var(--grid);
  border-radius: 8px;
  padding: 6px 10px;
  font-size: 12px;
  pointer-events: none;
  box-shadow: 0 2px 8px rgb(0 0 0 / 0.08);
  white-space: nowrap;
}
.tt-title {
  color: var(--text-secondary);
}
.tt-value {
  font-weight: 600;
  color: var(--text-primary);
}
</style>
