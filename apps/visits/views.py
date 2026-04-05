from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.contrib import messages
from django.views.decorators.http import require_POST

from apps.visits.models import Visit
from apps.charts.models import ChartNote
from apps.charts.forms import ChartNoteForm
from apps.ai_jobs.usecases import run_ai_draft
from apps.staff.decorators import staff_required

@staff_required
def visit_list(request):
    visits = Visit.objects.order_by("-visited_at")[:50]
    return render(request, "visits/visit_list.html", {"visits": visits})


def _get_or_create_note(visit) -> ChartNote:
    note = ChartNote.objects.filter(visit=visit).order_by("-version").first()
    if not note:
        note = ChartNote.objects.create(
            clinic=visit.clinic,
            visit=visit,
            version=1,
            state=ChartNote.State.DRAFT_AI,
            created_by=visit.practitioner,
        )
    return note


@login_required
def visit_detail(request, pk: int):
    visit = get_object_or_404(Visit, pk=pk)

    note = _get_or_create_note(visit)
    form = ChartNoteForm(instance=note)

    ctx = {
        "visit": visit,
        "note": note,
        "form": form,
    }
    return render(request, "visits/visit_detail.html", ctx)


@require_POST
@login_required
def visit_ai_draft(request, pk: int):
    visit = get_object_or_404(Visit, pk=pk)

    # まずは「診察メモ」を入力として使う（録音導入前の暫定）
    input_text = (getattr(visit, "memo", "") or "").strip()

    job = run_ai_draft(visit, input_text=input_text)

    if job.status == job.Status.SUCCESS:
        messages.success(request, "AI下書きを作成しました。")
    else:
        messages.error(request, f"AI下書きに失敗しました: {job.error_message}")

    return redirect("visits:detail", pk=visit.pk)


@require_POST
@login_required
def note_save(request, pk: int):
    visit = get_object_or_404(Visit, pk=pk)
    note = _get_or_create_note(visit)

    form = ChartNoteForm(request.POST, instance=note)
    if form.is_valid():
        form.save()
        messages.success(request, "カルテを保存しました。")
    else:
        messages.error(request, "入力内容にエラーがあります。")

    return redirect("visits:detail", pk=visit.pk)


@require_POST
@login_required
def note_finalize(request, pk: int):
    visit = get_object_or_404(Visit, pk=pk)
    note = _get_or_create_note(visit)

    note.state = ChartNote.State.FINAL  # ←あなたのEnum名に合わせて
    note.save(update_fields=["state"])
    messages.success(request, "カルテを確定しました。")

    return redirect("visits:detail", pk=visit.pk)
