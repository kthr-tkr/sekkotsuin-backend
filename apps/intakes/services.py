def intake_to_text(intake):
    if not intake:
        return ""

    p = intake.payload or {}
    lines = []

    body = p.get("body_parts") or []
    symptoms = p.get("symptoms") or []
    ps = p.get("pain_scale")
    onset = p.get("onset") or {}
    aggravating = p.get("aggravating_factors") or []
    relieving = p.get("relieving_factors") or []
    trigger = p.get("trigger") or []
    free = p.get("free_comment") or ""

    if body:
        lines.append(f"部位：{', '.join(body)}")
    if symptoms:
        lines.append(f"症状：{', '.join(symptoms)}")
    if ps is not None:
        lines.append(f"疼痛スケール：{ps}/10（来院前）")

    onset_line = " ".join([onset.get("timing", ""), onset.get("detail", "")]).strip()
    if onset_line:
        lines.append(f"発症：{onset_line}")

    if trigger:
        lines.append(f"きっかけ：{', '.join(trigger)}")
    if aggravating:
        lines.append(f"増悪因子：{', '.join(aggravating)}")
    if relieving:
        lines.append(f"軽減因子：{', '.join(relieving)}")
    if free:
        lines.append(f"自由記述：{free}")

    return "\n".join(lines).strip()
