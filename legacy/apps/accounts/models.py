from django.contrib.auth.models import AbstractUser
from django.db import models

class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "管理者"
        RECEPTION = "reception", "受付"
        PRACTITIONER = "practitioner", "施術者"
        PATIENT = "patient", "患者"
        

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="users",
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.PRACTITIONER,
    )