<script setup lang="ts">
/** 指・ペン・マウスで書けるサイン欄。toDataUrl() で PNG を返す。 */
const canvas = ref<HTMLCanvasElement | null>(null)
const empty = ref(true)
let drawing = false

function ctx() {
  return canvas.value!.getContext('2d')!
}

// ダイアログの表示アニメーション中は幅が 0 のことがあるため、表示サイズが変わったら作り直す
function resize() {
  const c = canvas.value
  if (!c) return
  const ratio = window.devicePixelRatio || 1
  const w = Math.round(c.clientWidth * ratio)
  const h = Math.round(c.clientHeight * ratio)
  if (c.width === w && c.height === h) return
  c.width = w
  c.height = h
  const g = ctx()
  g.scale(ratio, ratio)
  g.lineWidth = 2.5
  g.lineCap = 'round'
  g.lineJoin = 'round'
  g.strokeStyle = '#111'
  empty.value = true
}

function pos(e: PointerEvent) {
  const r = canvas.value!.getBoundingClientRect()
  return { x: e.clientX - r.left, y: e.clientY - r.top }
}

function down(e: PointerEvent) {
  if (empty.value) resize()
  drawing = true
  canvas.value!.setPointerCapture(e.pointerId)
  const p = pos(e)
  ctx().beginPath()
  ctx().moveTo(p.x, p.y)
}
function move(e: PointerEvent) {
  if (!drawing) return
  const p = pos(e)
  ctx().lineTo(p.x, p.y)
  ctx().stroke()
  empty.value = false
}
function up() {
  drawing = false
}

function clear() {
  const c = canvas.value!
  ctx().clearRect(0, 0, c.width, c.height)
  empty.value = true
}

/** 白背景の PNG（data URL） */
function toDataUrl(): string {
  const c = canvas.value!
  const out = document.createElement('canvas')
  out.width = c.width
  out.height = c.height
  const g = out.getContext('2d')!
  g.fillStyle = '#fff'
  g.fillRect(0, 0, out.width, out.height)
  g.drawImage(c, 0, 0)
  return out.toDataURL('image/png')
}

let observer: ResizeObserver | null = null
onMounted(() => {
  resize()
  observer = new ResizeObserver(() => {
    if (empty.value) resize()
  })
  observer.observe(canvas.value!)
})
onBeforeUnmount(() => observer?.disconnect())
defineExpose({ clear, toDataUrl, empty })
</script>

<template>
  <div>
    <canvas
      ref="canvas"
      class="pad"
      @pointerdown="down"
      @pointermove="move"
      @pointerup="up"
      @pointercancel="up"
    />
    <div class="d-flex justify-space-between align-center mt-1">
      <span class="text-caption text-medium-emphasis">枠内にサインしてください</span>
      <v-btn size="small" variant="text" prepend-icon="mdi-eraser" @click="clear">書き直す</v-btn>
    </div>
  </div>
</template>

<style scoped>
.pad {
  width: 100%;
  height: 200px;
  border: 2px dashed rgb(var(--v-theme-primary));
  border-radius: 8px;
  background: #fff;
  touch-action: none;
  display: block;
}
</style>
