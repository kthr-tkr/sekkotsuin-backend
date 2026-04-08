from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.apps import apps


class Command(BaseCommand):
    help = "単院版の初期セットアップを行う（Clinic 1件 + 管理者ユーザー作成/更新）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clinic-name",
            default="Nakano Clinic",
            help="作成または維持する Clinic 名",
        )
        parser.add_argument(
            "--admin-username",
            default="admin",
            help="管理者ユーザー名",
        )
        parser.add_argument(
            "--admin-email",
            default="",
            help="管理者メールアドレス",
        )
        parser.add_argument(
            "--admin-password",
            required=True,
            help="管理者パスワード",
        )
        parser.add_argument(
            "--delete-extra-clinics",
            action="store_true",
            help="指定Clinic以外のClinicを削除する",
        )
        parser.add_argument(
            "--noinput",
            action="store_true",
            help="確認プロンプトを出さずに実行する",
        )

    def handle(self, *args, **options):
        clinic_name = options["clinic_name"].strip()
        admin_username = options["admin_username"].strip()
        admin_email = (options["admin_email"] or "").strip()
        admin_password = options["admin_password"]
        delete_extra_clinics = options["delete_extra_clinics"]
        noinput = options["noinput"]

        if not clinic_name:
            raise CommandError("clinic-name は必須です。")
        if not admin_username:
            raise CommandError("admin-username は必須です。")
        if not admin_password:
            raise CommandError("admin-password は必須です。")

        Clinic = self._get_clinic_model()
        User = get_user_model()

        with transaction.atomic():
            clinic = self._get_or_create_clinic(Clinic, clinic_name)

            user, created = self._get_or_create_admin_user(
                User=User,
                username=admin_username,
                email=admin_email,
                password=admin_password,
                clinic=clinic,
            )

            if delete_extra_clinics:
                self._delete_extra_clinics(
                    Clinic=Clinic,
                    keep_clinic=clinic,
                    noinput=noinput,
                )

        self.stdout.write(self.style.SUCCESS("bootstrap_single_clinic 完了"))
        self.stdout.write(f"- Clinic: {clinic}")
        self.stdout.write(f"- Admin username: {getattr(user, 'username', '(unknown)')}")
        self.stdout.write(f"- Admin email: {getattr(user, 'email', '')}")

    def _get_clinic_model(self):
        """
        Clinic モデル取得。
        apps.clinics.models.Clinic を優先しつつ、
        万一 app_label が違う場合にも少しだけ耐性を持たせる。
        """
        try:
            return apps.get_model("clinics", "Clinic")
        except LookupError:
            raise CommandError(
                "Clinic モデルが見つかりません。"
                " app_label='clinics', model='Clinic' を確認してください。"
            )

    def _get_model_field_names(self, model):
        return {f.name for f in model._meta.get_fields() if hasattr(f, "name")}

    def _get_or_create_clinic(self, Clinic, clinic_name):
        field_names = self._get_model_field_names(Clinic)

        defaults = {}

        if "is_active" in field_names:
            defaults["is_active"] = True

        if "slug" in field_names:
            defaults["slug"] = self._slugify(clinic_name)

        if "code" in field_names:
            defaults["code"] = self._slugify(clinic_name).upper().replace("-", "_")[:50]

        clinic, created = Clinic.objects.get_or_create(
            name=clinic_name,
            defaults=defaults,
        )

        updated = False

        if "is_active" in field_names and getattr(clinic, "is_active", None) is False:
            clinic.is_active = True
            updated = True

        if "slug" in field_names and not getattr(clinic, "slug", ""):
            clinic.slug = self._slugify(clinic_name)
            updated = True

        if "code" in field_names and not getattr(clinic, "code", ""):
            clinic.code = self._slugify(clinic_name).upper().replace("-", "_")[:50]
            updated = True

        if updated:
            clinic.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f"Clinic を作成しました: {clinic_name}"))
        else:
            self.stdout.write(f"Clinic は既存を使用します: {clinic_name}")

        return clinic

    def _get_or_create_admin_user(self, User, username, email, password, clinic):
        user_field_names = self._get_model_field_names(User)

        lookup = {"username": username}
        defaults = {}

        if "email" in user_field_names:
            defaults["email"] = email

        user, created = User.objects.get_or_create(
            **lookup,
            defaults=defaults,
        )

        updated = False

        if "email" in user_field_names and email and getattr(user, "email", "") != email:
            user.email = email
            updated = True

        if hasattr(user, "is_active") and not user.is_active:
            user.is_active = True
            updated = True

        if hasattr(user, "is_staff") and not user.is_staff:
            user.is_staff = True
            updated = True

        if hasattr(user, "is_superuser") and not user.is_superuser:
            user.is_superuser = True
            updated = True

        # clinic 紐づけ（User に clinic FK がある場合）
        if "clinic" in user_field_names:
            current_clinic_id = getattr(user, "clinic_id", None)
            if current_clinic_id != clinic.id:
                user.clinic = clinic
                updated = True

        # role フィールドがある場合だけ軽く対応
        if "role" in user_field_names:
            current_role = getattr(user, "role", "")
            if current_role in ("", None):
                user.role = "admin"
                updated = True

        # パスワードは毎回再設定
        user.set_password(password)
        updated = True

        if created or updated:
            user.save()

        if created:
            self.stdout.write(self.style.SUCCESS(f"管理者ユーザーを作成しました: {username}"))
        else:
            self.stdout.write(f"管理者ユーザーは既存を更新しました: {username}")

        return user, created

    def _delete_extra_clinics(self, Clinic, keep_clinic, noinput=False):
        qs = Clinic.objects.exclude(pk=keep_clinic.pk).order_by("pk")
        count = qs.count()

        if count == 0:
            self.stdout.write("削除対象の余分な Clinic はありません。")
            return

        self.stdout.write(self.style.WARNING("削除対象の Clinic:"))
        for clinic in qs:
            self.stdout.write(f"  - {clinic}")

        if not noinput:
            confirm = input("上記の Clinic を削除しますか？ [y/N]: ").strip().lower()
            if confirm != "y":
                self.stdout.write(self.style.WARNING("Clinic 削除を中止しました。"))
                return

        deleted_count = 0
        for clinic in qs:
            clinic.delete()
            deleted_count += 1

        self.stdout.write(self.style.SUCCESS(f"{deleted_count} 件の余分な Clinic を削除しました。"))

    def _slugify(self, text):
        text = (text or "").strip().lower()
        safe = []
        prev_dash = False

        for ch in text:
            if ch.isalnum():
                safe.append(ch)
                prev_dash = False
            else:
                if not prev_dash:
                    safe.append("-")
                    prev_dash = True

        slug = "".join(safe).strip("-")
        return slug or "clinic"