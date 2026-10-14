<script setup lang="ts">
/** 姿勢写真。グリッド線（縦の中心線と水平線）を重ねて左右差・傾きを見やすくする。 */
defineProps<{ src?: string; label: string; grid?: boolean }>()
</script>

<template>
  <div class="photo">
    <div class="photo-label">{{ label }}</div>
    <div v-if="src" class="frame">
      <img :src="src" :alt="label" />
      <svg v-if="grid" class="grid" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
        <line x1="50" y1="0" x2="50" y2="100" class="center" />
        <line v-for="y in [10, 20, 30, 40, 50, 60, 70, 80, 90]" :key="y" x1="0" :y1="y" x2="100" :y2="y" />
        <line v-for="x in [25, 75]" :key="x" :x1="x" y1="0" :x2="x" y2="100" />
      </svg>
    </div>
    <div v-else class="frame empty">
      <v-icon icon="mdi-camera-outline" size="40" color="grey" />
      <div class="text-caption text-medium-emphasis">未撮影</div>
    </div>
    <slot />
  </div>
</template>

<style scoped>
.photo-label {
  font-weight: 600;
  margin-bottom: 4px;
}
.frame {
  position: relative;
  aspect-ratio: 3 / 4;
  background: #f1f1ef;
  border-radius: 8px;
  overflow: hidden;
}
.frame img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  display: block;
}
.frame.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
}
.grid {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
.grid line {
  stroke: rgb(255 255 255 / 0.7);
  stroke-width: 0.3;
  vector-effect: non-scaling-stroke;
}
.grid line.center {
  stroke: rgb(220 38 38 / 0.85);
  stroke-width: 1.5;
}
</style>
