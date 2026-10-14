/** 予約からカルテを開く（無ければ作成）して編集画面へ移動する。 */
export async function openClinicalNoteForAppointment(appointmentId: number) {
  const { data, error } = await useApi().POST('/api/clinical-notes', {
    body: { appointment_id: appointmentId },
  })
  if (error || !data) return errorMessage(error)
  await navigateTo(`/clinical-notes/${data.id}`)
  return null
}
