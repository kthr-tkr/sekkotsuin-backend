<script setup lang="ts">
/**
 * 施術前後の痛み（PS 0〜10）の推移。
 * 2系列の折れ線（凡例＋線末の値ラベル）、来院ごとのホバーでツールチップを表示する。
 * 表形式のデータは呼び出し側の経過テーブルが兼ねる。
 */
type Point = { date: string; before: number | null; after: number | null }
const props = defineProps<{ points: Point[] }>()

const W = 640
const H = 220
const M = { top: 16, right: 56, bottom: 28, left: 32 }
const iw = W - M.left - M.right
const ih = H - M.top - M.bottom

const SERIES = [
  { key: 'before', label: '施術前', color: 'var(--series-1)' },
  { key: 'after', label: '施術後', color: 'var(--series-2)' },
] as const

const x = (i: number) =>
  M.left + (props.points.length <= 1 ? iw / 2 : (i / (props.points.length - 1)) * iw)
const y = (v: number) => M.top + ih - (v / 10) * ih

function path(key: 'before' | 'after') {
  let d = ''
  let pen = false
  props.points.forEach((p, i) => {
    const v = p[key]
    if (v == null) {
      pen = false
      return
    }
    d += `${pen ? 'L' : 'M'}${x(i)},${y(v)}`
    pen = true
  })
  return d
}

function lastValue(key: 'before' | 'after') {
  for (let i = props.points.length - 1; i >= 0; i--) {
    const v = props.points[i]![key]
    if (v != null) return { i, v }
  }
  return null
}

const dateLabel = (iso: string) => {
  const [, m, d] = iso.slice(0, 10).split('-')
  return `${Number(m)}/${Number(d)}`
}
// ラベルが重ならないよう最大 8 個程度に間引く
const tickEvery = computed(() => Math.max(1, Math.ceil(props.points.length / 8)))

const hover = ref<number | null>(null)
const band = computed(() => (props.points.length <= 1 ? iw : iw / (props.points.length - 1)))
</script>

<template>
  <div class="viz-root">
    <div class="legend">
      <span v-for="s in SERIES" :key="s.key" class="legend-item">
        <svg width="18" height="10" aria-hidden="true">
          <line x1="1" y1="5" x2="17" y2="5" :stroke="s.color" stroke-width="2" stroke-linecap="round" />
        </svg>
        {{ s.label }}
      </span>
    </div>
    <div class="chart-wrap">
      <svg :viewBox="`0 0 ${W} ${H}`" role="img" aria-label="施術前後の痛み（PS）の推移" class="chart">
        <!-- grid -->
        <g>
          <template v-for="v in [0, 5, 10]" :key="v">
            <line :x1="M.left" :x2="W - M.right" :y1="y(v)" :y2="y(v)" class="grid" />
            <text :x="M.left - 8" :y="y(v)" class="axis" text-anchor="end" dominant-baseline="middle">
              {{ v }}
            </text>
          </template>
          <template v-for="(p, i) in points" :key="`t${i}`">
            <text
              v-if="i % tickEvery === 0 || i === points.length - 1"
              :x="x(i)"
              :y="H - 8"
              class="axis"
              text-anchor="middle"
            >
              {{ dateLabel(p.date) }}
            </text>
          </template>
        </g>

        <!-- crosshair -->
        <line
          v-if="hover !== null"
          :x1="x(hover)"
          :x2="x(hover)"
          :y1="M.top"
          :y2="M.top + ih"
          class="crosshair"
        />

        <!-- series -->
        <g v-for="s in SERIES" :key="s.key">
          <path :d="path(s.key)" fill="none" :stroke="s.color" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />
          <template v-for="(p, i) in points" :key="`${s.key}${i}`">
            <circle
              v-if="p[s.key] != null"
              :cx="x(i)"
              :cy="y(p[s.key]!)"
              :r="hover === i ? 5 : 4"
              :fill="s.color"
              class="marker"
            />
          </template>
          <text
            v-if="lastValue(s.key)"
            :x="x(lastValue(s.key)!.i) + 10"
            :y="y(lastValue(s.key)!.v)"
            class="end-label"
            dominant-baseline="middle"
          >
            {{ lastValue(s.key)!.v }}
          </text>
        </g>

        <!-- hit targets（マーカーより広い来院ごとの縦帯） -->
        <rect
          v-for="(p, i) in points"
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
        :style="{ left: `${(x(hover) / W) * 100}%`, top: '0' }"
      >
        <div class="tt-title">{{ formatDate(points[hover]!.date) }}</div>
        <div v-for="s in SERIES" :key="s.key" class="tt-row">
          <svg width="14" height="8" aria-hidden="true">
            <line x1="1" y1="4" x2="13" y2="4" :stroke="s.color" stroke-width="2" />
          </svg>
          <span class="tt-label">{{ s.label }}</span>
          <span class="tt-value">{{ points[hover]![s.key] ?? '-' }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.viz-root {
  max-width: 760px;
  --surface-1: #fcfcfb;
  --text-primary: #0b0b0b;
  --text-secondary: #52514e;
  --grid: #e6e5e1;
  --series-1: #2a78d6;
  --series-2: #eb6834;
  color: var(--text-primary);
}
.legend {
  display: flex;
  gap: 16px;
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.chart-wrap {
  position: relative;
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
.crosshair {
  stroke: var(--text-secondary);
  stroke-width: 1;
  opacity: 0.4;
}
.marker {
  stroke: var(--surface-1);
  stroke-width: 2;
}
.end-label {
  font-size: 12px;
  font-weight: 600;
  fill: var(--text-primary);
}
.tooltip {
  position: absolute;
  transform: translate(-50%, 0);
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
  margin-bottom: 2px;
}
.tt-row {
  display: flex;
  align-items: center;
  gap: 6px;
}
.tt-label {
  color: var(--text-secondary);
}
.tt-value {
  margin-left: auto;
  padding-left: 12px;
  font-weight: 600;
}
</style>
