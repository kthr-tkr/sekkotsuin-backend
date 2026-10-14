# apps/patients/models.py
from django.db import models
from django.conf import settings

class Patient(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="patient_profile",
    )

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="patients",
    )

    card_no = models.CharField(
        max_length=20,
        unique=True,
        editable=False,
    )

    last_name = models.CharField(max_length=50)
    first_name = models.CharField(max_length=50)
    last_name_kana = models.CharField(max_length=50)
    first_name_kana = models.CharField(max_length=50)

    birth_date = models.DateField()
    phone = models.CharField(max_length=20)
    address = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def clean(self):
        from django.core.exceptions import ValidationError
        errors = {}

        if self.user:
            if self.user.role != self.user.Role.PATIENT:
                errors["user"] = "患者プロフィールには patient ロールのユーザーのみ紐づけできます。"
            if self.user.clinic_id != self.clinic_id:
                errors["user"] = "患者ユーザーと患者プロフィールの院が一致していません。"

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.last_name} {self.first_name}"
