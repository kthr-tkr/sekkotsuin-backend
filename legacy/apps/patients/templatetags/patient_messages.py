from django import template


register = template.Library()

PATIENT_LOGIN_ONLY_TEXTS = {
    "メールアドレスまたは診察券番号、もしくはパスワードが正しくありません。",
    "ログインしてください。",
    "セッションが切れました。",
    "ログアウトしました。",
    "アカウントが無効です。",
    "患者用アカウントではありません。",
}
PATIENT_INTERNAL_MESSAGE_MARKERS = (
    "スタッフを登録",
    "スタッフを無効化",
    "スタッフを再有効化",
    "スタッフシフト",
    "施術メニュー",
    "院設定を保存",
    "売上実績",
    "カルテ案",
    "共有URL",
    "AI利用",
    "OpenAI",
    "traceback",
    "生JSON",
)


@register.filter
def is_patient_login_message(message):
    tags = str(getattr(message, "tags", "") or "").split()
    return (
        "patient-login" in tags
        or str(message).strip() in PATIENT_LOGIN_ONLY_TEXTS
        or any(
            marker in str(message)
            for marker in PATIENT_INTERNAL_MESSAGE_MARKERS
        )
    )
