from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("appointments", "0004_appointment_treatment_plan"),
    ]

    operations = [
        migrations.AddField(
            model_name="appointment",
            name="booking_source",
            field=models.CharField(
                choices=[
                    ("hp", "HP"),
                    ("line", "LINE"),
                    ("google", "Google"),
                    ("instagram", "Instagram"),
                    ("qr", "院内QR"),
                    ("flyer", "チラシ"),
                    ("referral", "紹介"),
                    ("sms", "SMS"),
                    ("email", "メール"),
                    ("staff", "スタッフ登録"),
                    ("unknown", "不明"),
                    ("other", "その他"),
                ],
                db_index=True,
                default="unknown",
                max_length=20,
                verbose_name="予約流入元",
            ),
        ),
    ]
