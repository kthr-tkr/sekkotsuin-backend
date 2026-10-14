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
