const TZ = 'Asia/Tokyo'

export const ROLE_LABELS: Record<string, string> = {
  admin: '管理者',
  reception: '受付',
  practitioner: '施術者',
}

export const STATUS_LABELS: Record<string, string> = {
  pending: '問診待ち',
  booked: '予約確定',
  arrived: '来院',
  completed: '完了',
  cancelled: 'キャンセル',
  no_show: '無断キャンセル',
}

export const STATUS_COLORS: Record<string, string> = {
  pending: '#F59E0B',
  booked: '#1D4ED8',
  arrived: '#16A34A',
  completed: '#64748B',
  cancelled: '#CBD5E1',
  no_show: '#DC2626',
}

export const SYMPTOM_LABELS: Record<string, string> = {
  acute: '急性',
  chronic: '慢性',
  unknown: '不明',
}

export const BOOKING_SOURCE_LABELS: Record<string, string> = {
  hp: 'HP',
  line: 'LINE',
  google: 'Google',
  instagram: 'Instagram',
  qr: '院内QR',
  flyer: 'チラシ',
  referral: '紹介',
  sms: 'SMS',
  email: 'メール',
  staff: 'スタッフ登録',
  unknown: '不明',
  other: 'その他',
}

export const PAIN_AREAS: { value: string; title: string }[] = [
  { value: 'neck', title: '首' },
  { value: 'shoulder', title: '肩' },
  { value: 'back', title: '背中' },
  { value: 'lower_back', title: '腰' },
  { value: 'hip', title: '股関節・お尻' },
  { value: 'knee', title: '膝' },
  { value: 'ankle', title: '足首' },
  { value: 'elbow', title: '肘' },
  { value: 'wrist', title: '手首' },
  { value: 'other', title: 'その他' },
]

export const toItems = (labels: Record<string, string>) =>
  Object.entries(labels).map(([value, title]) => ({ value, title }))

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '-'
  return new Intl.DateTimeFormat('ja-JP', {
    timeZone: TZ,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(iso))
}

export function formatTime(iso: string): string {
  return new Intl.DateTimeFormat('ja-JP', { timeZone: TZ, hour: '2-digit', minute: '2-digit' })
    .format(new Date(iso))
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '-'
  return new Intl.DateTimeFormat('ja-JP', { timeZone: TZ, dateStyle: 'medium' }).format(
    new Date(iso),
  )
}

/** 年齢（誕生日 YYYY-MM-DD から） */
export function ageOf(birthDate: string): number {
  const [y, m, d] = birthDate.split('-').map(Number) as [number, number, number]
  const now = new Date()
  let age = now.getFullYear() - y
  if (now.getMonth() + 1 < m || (now.getMonth() + 1 === m && now.getDate() < d)) age--
  return age
}

/** ローカル日時入力（YYYY-MM-DDTHH:mm, JST）→ ISO 文字列（+09:00） */
export function jstInputToIso(local: string): string {
  return `${local}:00+09:00`
}

/** ISO 文字列 → ローカル日時入力用（YYYY-MM-DDTHH:mm, JST） */
export function isoToJstInput(iso: string): string {
  const parts = new Intl.DateTimeFormat('sv-SE', {
    timeZone: TZ,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(new Date(iso))
  return parts.replace(' ', 'T')
}

export const patientName = (p: { last_name: string; first_name: string } | null | undefined) =>
  p ? `${p.last_name} ${p.first_name}` : '（患者未設定）'

export const NOTE_STATUS_LABELS: Record<string, string> = {
  draft: '下書き',
  finalized: '確定',
}

export const NOTE_STATUS_COLORS: Record<string, string> = {
  draft: 'warning',
  finalized: 'success',
}

export const SOAP_FIELDS = [
  { key: 'subjective', label: 'S（主観）', hint: '患者の訴え・症状の経過' },
  { key: 'objective', label: 'O（客観）', hint: '視診・触診・検査所見' },
  { key: 'assessment', label: 'A（評価）', hint: '見立て・考えられる原因' },
  { key: 'plan', label: 'P（計画）', hint: '今後の施術方針・通院頻度' },
] as const

export const PLAN_STATUS_LABELS: Record<string, string> = {
  active: '進行中',
  paused: '中断',
  completed: '完了',
}

export const PLAN_STATUS_COLORS: Record<string, string> = {
  active: 'primary',
  paused: 'warning',
  completed: 'grey',
}

export const VISIT_GUIDE_LABELS: Record<string, string> = {
  daily: '毎日',
  weekly: '週',
  monthly: '月',
  custom: '個別設定',
}

export function visitGuideText(p: {
  visit_guide_type?: string | null
  visit_guide_count?: number | null
  visit_guide_note?: string
}): string {
  const t = p.visit_guide_type
  let base = ''
  if (t === 'daily') base = '毎日'
  else if ((t === 'weekly' || t === 'monthly') && p.visit_guide_count)
    base = `${VISIT_GUIDE_LABELS[t]}${p.visit_guide_count}回`
  else if (t) base = VISIT_GUIDE_LABELS[t] ?? ''
  return [base, p.visit_guide_note].filter(Boolean).join('（') + (base && p.visit_guide_note ? '）' : '')
}

export const PLAN_INSTRUCTIONS = [
  { key: 'bath_instruction', label: '入浴について' },
  { key: 'walking_instruction', label: '歩行について' },
  { key: 'exercise_instruction', label: '運動について' },
  { key: 'work_instruction', label: '仕事について' },
  { key: 'lifestyle_instruction', label: '日常生活について' },
  { key: 'caution_notes', label: 'その他の注意事項' },
] as const

export const POSTURE_VIEWS = [
  { value: 'front', title: '正面' },
  { value: 'side_right', title: '右側面' },
  { value: 'side_left', title: '左側面' },
  { value: 'back', title: '背面' },
] as const

export const POSTURE_REGIONS = [
  { key: 'head_neck', label: '頭部・頸部' },
  { key: 'shoulder', label: '肩・肩甲帯' },
  { key: 'spine', label: '脊柱・体幹' },
  { key: 'pelvis', label: '骨盤' },
  { key: 'hip', label: '股関節' },
  { key: 'knee', label: '膝' },
  { key: 'ankle_foot', label: '足関節・足部' },
  { key: 'balance', label: '全体バランス' },
] as const
