import math


DEFAULT_TREND_THRESHOLD = 0.5


def _as_number(value):
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None

    return None


def _build_measurement_comparison(before_value, after_value, threshold):
    before_number = _as_number(before_value)
    after_number = _as_number(after_value)

    if before_number is None or after_number is None:
        return {
            "before": before_value,
            "after": after_value,
            "delta": None,
            "trend": "unknown",
        }

    delta = round(after_number - before_number, 2)
    magnitude_change = abs(after_number) - abs(before_number)

    if abs(magnitude_change) < threshold:
        trend = "unchanged"
    elif magnitude_change < 0:
        trend = "improved"
    else:
        trend = "worsened"

    return {
        "before": before_value,
        "after": after_value,
        "delta": delta,
        "trend": trend,
    }


def build_posture_comparison_json(
    comparison,
    threshold=DEFAULT_TREND_THRESHOLD,
):
    before_images = {
        image.image_type: image
        for image in comparison.before_assessment.images.all()
    }
    after_images = {
        image.image_type: image
        for image in comparison.after_assessment.images.all()
    }

    comparison_items = {}

    for image_type in sorted(before_images.keys() & after_images.keys()):
        before_measurements = (
            before_images[image_type].measurements_json or {}
        ).get("items") or {}
        after_measurements = (
            after_images[image_type].measurements_json or {}
        ).get("items") or {}

        image_items = {}

        for measurement_key in sorted(
            before_measurements.keys() & after_measurements.keys()
        ):
            image_items[measurement_key] = _build_measurement_comparison(
                before_measurements[measurement_key],
                after_measurements[measurement_key],
                threshold,
            )

        if image_items:
            comparison_items[image_type] = image_items

    return {
        "version": 1,
        "items": comparison_items,
    }
