from django.apps import AppConfig

class ChartsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.charts"

    def ready(self):
        # signals を登録
        from . import signals  # noqa
