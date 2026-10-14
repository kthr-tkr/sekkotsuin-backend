<script setup lang="ts">
import type { Schemas } from '~/composables/useApi'

type Rec = Schemas['RecordingOut']

const props = defineProps<{
  noteId: number
  /** 反映前に呼ぶ（カルテの未保存の変更を保存する）。false なら中止 */
  beforeApply?: () => Promise<boolean>
}>()
const emit = defineEmits<{ applied: [] }>()
const api = useApi()

const { data: recordings, refresh } = await useAsyncData(`note-${props.noteId}-recordings`, async () => {
  const { data } = await api.GET('/api/clinical-notes/{note_id}/recordings', {
    params: { path: { note_id: props.noteId } },
  })
  return data ?? []
})

const PENDING = ['queued', 'transcribing', 'summarizing']
const STATUS_TEXT: Record<string, string> = {
  queued: '処理待ち',
  transcribing: '文字起こし中',
  summarizing: '要約中',
  done: '完了',
  failed: '失敗',
}

// 処理中の録音があれば 3 秒ごとに更新する
let timer: ReturnType<typeof setInterval> | undefined
watchEffect(() => {
  const busy = recordings.value?.some((r) => PENDING.includes(r.status))
  if (busy && !timer) timer = setInterval(refresh, 3000)
  if (!busy && timer) {
    clearInterval(timer)
    timer = undefined
  }
})

// 録音
const recorder = ref<MediaRecorder | null>(null)
const elapsed = ref(0)
const error = ref<string | null>(null)
const uploading = ref(false)
let chunks: Blob[] = []
let startedAt = 0
let tick: ReturnType<typeof setInterval> | undefined

function pickMime() {
  for (const t of ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg']) {
    if (MediaRecorder.isTypeSupported(t)) return t
  }
  return ''
}

async function start() {
  error.value = null
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mimeType = pickMime()
    const r = new MediaRecorder(stream, mimeType ? { mimeType } : undefined)
    chunks = []
    r.ondataavailable = (e) => e.data.size && chunks.push(e.data)
    r.onstop = () => {
      stream.getTracks().forEach((t) => t.stop())
      upload(new Blob(chunks, { type: r.mimeType }), Math.max(1, Math.round((Date.now() - startedAt) / 1000)))
    }
    r.start(1000)
    startedAt = Date.now()
    elapsed.value = 0
    tick = setInterval(() => (elapsed.value = Math.round((Date.now() - startedAt) / 1000)), 500)
    recorder.value = r
  } catch {
    error.value = 'マイクを使えませんでした。ブラウザのマイクの許可を確認してください。'
  }
}

function stop() {
  clearInterval(tick)
  recorder.value?.stop()
  recorder.value = null
}

async function upload(blob: Blob, durationSec: number) {
  uploading.value = true
  const fd = new FormData()
  const ext = blob.type.includes('mp4') ? 'm4a' : blob.type.includes('ogg') ? 'ogg' : 'webm'
  fd.append('file', blob, `recording.${ext}`)
  fd.append('duration_sec', String(durationSec))
  const { error: err } = await api.POST('/api/clinical-notes/{note_id}/recordings', {
    params: { path: { note_id: props.noteId } },
    body: fd as unknown as { file: string; duration_sec: number },
    bodySerializer: (b) => b as unknown as FormData,
  })
  uploading.value = false
  if (err) error.value = errorMessage(err)
  await refresh()
}

async function apply(r: Rec) {
  if (props.beforeApply && !(await props.beforeApply())) return
  const { error: err } = await api.POST('/api/recordings/{recording_id}/apply', {
    params: { path: { recording_id: r.id } },
  })
  if (err) error.value = errorMessage(err)
  await refresh()
  emit('applied')
}

async function retry(r: Rec) {
  const { error: err } = await api.POST('/api/recordings/{recording_id}/retry', {
    params: { path: { recording_id: r.id } },
  })
  if (err) error.value = errorMessage(err)
  await refresh()
}

onBeforeUnmount(() => {
  clearInterval(timer)
  clearInterval(tick)
  recorder.value?.stop()
})

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
type Summary = {
  soap?: Record<'S' | 'O' | 'A' | 'P', string[]>
  red_flags?: string[]
  followups?: string[]
}
const summaryOf = (r: Rec) => r.summary as Summary
</script>

<template>
  <v-card title="録音して AI でカルテ下書き">
    <v-card-text>
      <p class="text-body-medium text-medium-emphasis mb-3">
        問診や施術中の会話を録音すると、文字起こしと SOAP の下書きを作ります。内容を確認してからカルテに反映してください。
      </p>
      <div class="d-flex align-center ga-3 mb-2">
        <v-btn
          v-if="!recorder"
          color="error"
          prepend-icon="mdi-microphone"
          :loading="uploading"
          @click="start"
        >
          録音開始
        </v-btn>
        <v-btn v-else color="error" variant="flat" prepend-icon="mdi-stop" @click="stop">
          停止して送信
        </v-btn>
        <span v-if="recorder" class="text-title-large font-weight-bold" aria-live="polite">
          <v-icon icon="mdi-record" color="error" size="small" /> {{ mmss(elapsed) }}
        </span>
      </div>
      <v-alert v-if="error" type="error" variant="tonal" density="compact" class="mb-2" :text="error" />

      <v-card v-for="r in recordings" :key="r.id" variant="outlined" class="mt-3">
        <v-card-item>
          <v-card-title class="text-title-small">
            {{ formatDateTime(r.created_at) }}（{{ mmss(r.duration_sec) }}）
          </v-card-title>
          <template #append>
            <v-chip
              size="small"
              :color="r.status === 'done' ? 'success' : r.status === 'failed' ? 'error' : 'info'"
              variant="tonal"
            >
              <v-progress-circular v-if="PENDING.includes(r.status)" indeterminate size="12" width="2" class="mr-1" />
              {{ STATUS_TEXT[r.status] }}
            </v-chip>
          </template>
        </v-card-item>
        <v-card-text class="pt-0">
          <audio v-if="r.audio_url" :src="fileUrl(r.audio_url)" controls preload="none" class="w-100 mb-2" />
          <template v-if="r.status === 'failed'">
            <v-alert type="error" variant="tonal" density="compact" :text="r.error_message" class="mb-2" />
            <v-btn size="small" variant="tonal" @click="retry(r)">再実行</v-btn>
          </template>
          <template v-if="r.status === 'done'">
            <v-alert
              v-if="summaryOf(r).red_flags?.length"
              type="warning"
              variant="tonal"
              density="compact"
              title="受診を勧めるべき兆候の可能性"
              class="mb-2"
            >
              <div v-for="f in summaryOf(r).red_flags" :key="f">・{{ f }}</div>
            </v-alert>
            <div v-for="k in ['S', 'O', 'A', 'P'] as const" :key="k" class="mb-1">
              <strong>{{ k }}</strong>
              <span v-if="!summaryOf(r).soap?.[k]?.length" class="text-medium-emphasis">（なし）</span>
              <div v-for="line in summaryOf(r).soap?.[k] ?? []" :key="line" class="ml-3">・{{ line }}</div>
            </div>
            <div v-if="summaryOf(r).followups?.length" class="mt-2 text-body-medium">
              <strong>次回確認:</strong> {{ summaryOf(r).followups!.join(' / ') }}
            </div>
            <v-expansion-panels class="mt-2">
              <v-expansion-panel title="文字起こし全文">
                <v-expansion-panel-text style="white-space: pre-wrap">{{ r.transcript }}</v-expansion-panel-text>
              </v-expansion-panel>
            </v-expansion-panels>
            <div class="d-flex justify-end mt-2">
              <v-btn
                :color="r.applied_at ? undefined : 'primary'"
                :variant="r.applied_at ? 'text' : 'flat'"
                prepend-icon="mdi-file-import-outline"
                @click="apply(r)"
              >
                {{ r.applied_at ? 'もう一度反映' : 'カルテに反映' }}
              </v-btn>
            </div>
          </template>
        </v-card-text>
      </v-card>
    </v-card-text>
  </v-card>
</template>
