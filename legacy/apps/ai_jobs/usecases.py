from django.utils import timezone
from django.db import transaction
from django.conf import settings

from apps.charts.models import ChartNote
from apps.intakes.services.ai_summarizer import intake_to_text
from .models import AudioJob
from .services_openai import generate_soap_openai
from .safety import sanitize_soap


@transaction.atomic
def run_ai_draft(visit, input_text: str) -> AudioJob:
    job = AudioJob.objects.create(
        clinic=visit.clinic,
        visit=visit,
        status=AudioJob.Status.PROCESSING,
        input_text=input_text,
        started_at=timezone.now(),
    )

    try:
        # ✅ キーは実行時にチェック
        if not getattr(settings, "OPENAI_API_KEY", ""):
            raise RuntimeError("OPENAI_API_KEY が設定されていません。(.env / 環境変数を確認)")

        # 対象のカルテ（基本 v1）を取得。無ければ作る（保険）
        note = ChartNote.objects.filter(visit=visit).order_by("version").first()
        if not note:
            note = ChartNote.objects.create(
                clinic=visit.clinic,
                visit=visit,
                version=1,
                state=ChartNote.State.DRAFT_AI,
                created_by=visit.practitioner,
            )

        intake_text = intake_to_text(visit.intake)

        # ① OpenAIでSOAP生成（生データ）
        soap = generate_soap_openai(
            intake_text=intake_text,
            exam_text=input_text,
            model=getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
        )

        raw = {"s": soap.s, "o": soap.o, "a": soap.a, "p": soap.p}

        # ② ルールベースで安全化（置換＆検知ログ）
        cleaned, hits = sanitize_soap(raw)

        # ③ jobへ保存（監査・デバッグ）
        job.ai_output_json = raw
        job.safety_hits = [h.__dict__ for h in hits]

        # ④ ChartNoteへ保存（安全化後）
        note.subjective_text = cleaned["s"]
        note.objective_text = cleaned["o"]
        note.assessment_text = cleaned["a"]
        note.plan_text = cleaned["p"]
        note.state = ChartNote.State.DRAFT_AI
        note.save()

        job.status = AudioJob.Status.SUCCESS
        job.finished_at = timezone.now()
        job.save()
        return job

    except Exception as e:
        job.status = AudioJob.Status.FAILED
        job.error_message = str(e)
        job.finished_at = timezone.now()
        job.save()
        return job
