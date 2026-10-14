# apps/posture_assessments/services/measurements.py

import math


def _valid_image_dimensions(image_width, image_height):
    try:
        width = float(image_width)
        height = float(image_height)
    except (TypeError, ValueError):
        return None, None

    if width <= 0 or height <= 0:
        return None, None

    return width, height


def _angle_deg(p1, p2, image_width=None, image_height=None):
    width, height = _valid_image_dimensions(image_width, image_height)
    x_scale = width if width is not None else 1.0
    y_scale = height if height is not None else 1.0

    dx = (p2["x"] - p1["x"]) * x_scale
    dy = (p2["y"] - p1["y"]) * y_scale
    return round(math.degrees(math.atan2(dy, dx)), 2)


def _distance(p1, p2):
    dx = p2["x"] - p1["x"]
    dy = p2["y"] - p1["y"]
    return round(math.sqrt(dx * dx + dy * dy), 2)


def _midpoint(p1, p2):
    return {
        "x": round((p1["x"] + p2["x"]) / 2, 2),
        "y": round((p1["y"] + p2["y"]) / 2, 2),
    }


def _slope_deg(left, right, image_width=None, image_height=None):
    return _angle_deg(
        left,
        right,
        image_width=image_width,
        image_height=image_height,
    )


def _build_result(image_type, items, image_width=None, image_height=None):
    width, height = _valid_image_dimensions(image_width, image_height)

    return {
        "version": 2,
        "image_type": image_type,
        "coordinate_unit": "percent",
        "image_dimensions": {
            "width": round(width, 2) if width is not None else None,
            "height": round(height, 2) if height is not None else None,
        },
        "angle_aspect_ratio_applied": width is not None and height is not None,
        "items": items,
    }


def build_measurements_for_image(
    image_type,
    points,
    image_width=None,
    image_height=None,
):
    if image_type == "front":
        return build_front_measurements(
            points,
            image_width=image_width,
            image_height=image_height,
        )

    if image_type == "side_right":
        return build_side_right_measurements(
            points,
            image_width=image_width,
            image_height=image_height,
        )

    if image_type == "back":
        return build_back_measurements(
            points,
            image_width=image_width,
            image_height=image_height,
        )

    return _build_result(
        image_type,
        {},
        image_width=image_width,
        image_height=image_height,
    )


def build_front_measurements(points, image_width=None, image_height=None):
    items = {}

    if "left_shoulder" in points and "right_shoulder" in points:
        items["shoulder_slope_deg"] = _slope_deg(
            points["left_shoulder"],
            points["right_shoulder"],
            image_width=image_width,
            image_height=image_height,
        )
        items["shoulder_height_diff_pct"] = round(
            points["left_shoulder"]["y"] - points["right_shoulder"]["y"],
            2,
        )

    if "left_hip" in points and "right_hip" in points:
        items["pelvis_slope_deg"] = _slope_deg(
            points["left_hip"],
            points["right_hip"],
            image_width=image_width,
            image_height=image_height,
        )
        items["pelvis_height_diff_pct"] = round(
            points["left_hip"]["y"] - points["right_hip"]["y"],
            2,
        )

    if all(k in points for k in ["left_shoulder", "right_shoulder", "left_hip", "right_hip"]):
        shoulder_mid = _midpoint(points["left_shoulder"], points["right_shoulder"])
        hip_mid = _midpoint(points["left_hip"], points["right_hip"])
        items["trunk_center_shift_pct"] = round(shoulder_mid["x"] - hip_mid["x"], 2)
        items["trunk_axis_deg"] = _angle_deg(
            hip_mid,
            shoulder_mid,
            image_width=image_width,
            image_height=image_height,
        )

    if all(k in points for k in ["left_hip", "left_knee", "left_ankle"]):
        items["left_lower_limb_axis_deg"] = _angle_deg(
            points["left_hip"],
            points["left_ankle"],
            image_width=image_width,
            image_height=image_height,
        )
        items["left_knee_medial_shift_pct"] = round(
            points["left_knee"]["x"] - ((points["left_hip"]["x"] + points["left_ankle"]["x"]) / 2),
            2,
        )

    if all(k in points for k in ["right_hip", "right_knee", "right_ankle"]):
        items["right_lower_limb_axis_deg"] = _angle_deg(
            points["right_hip"],
            points["right_ankle"],
            image_width=image_width,
            image_height=image_height,
        )
        items["right_knee_medial_shift_pct"] = round(
            points["right_knee"]["x"] - ((points["right_hip"]["x"] + points["right_ankle"]["x"]) / 2),
            2,
        )

    return _build_result(
        "front",
        items,
        image_width=image_width,
        image_height=image_height,
    )


def build_side_right_measurements(points, image_width=None, image_height=None):
    items = {}

    if "ear" in points and "shoulder" in points:
        items["forward_head_shift_pct"] = round(
            points["ear"]["x"] - points["shoulder"]["x"],
            2,
        )
        items["ear_shoulder_angle_deg"] = _angle_deg(
            points["shoulder"],
            points["ear"],
            image_width=image_width,
            image_height=image_height,
        )

    if "shoulder" in points and "hip" in points:
        items["trunk_lean_deg"] = _angle_deg(
            points["hip"],
            points["shoulder"],
            image_width=image_width,
            image_height=image_height,
        )

    if "hip" in points and "knee" in points:
        items["hip_knee_axis_deg"] = _angle_deg(
            points["hip"],
            points["knee"],
            image_width=image_width,
            image_height=image_height,
        )

    if "knee" in points and "ankle" in points:
        items["knee_ankle_axis_deg"] = _angle_deg(
            points["ankle"],
            points["knee"],
            image_width=image_width,
            image_height=image_height,
        )

    if all(k in points for k in ["shoulder", "hip", "knee", "ankle"]):
        items["body_stack_score_hint"] = round(
            abs(points["shoulder"]["x"] - points["hip"]["x"])
            + abs(points["hip"]["x"] - points["knee"]["x"])
            + abs(points["knee"]["x"] - points["ankle"]["x"]),
            2,
        )

    return _build_result(
        "side_right",
        items,
        image_width=image_width,
        image_height=image_height,
    )


def build_back_measurements(points, image_width=None, image_height=None):
    items = {}

    if "left_shoulder" in points and "right_shoulder" in points:
        items["back_shoulder_slope_deg"] = _slope_deg(
            points["left_shoulder"],
            points["right_shoulder"],
            image_width=image_width,
            image_height=image_height,
        )
        items["back_shoulder_height_diff_pct"] = round(
            points["left_shoulder"]["y"] - points["right_shoulder"]["y"],
            2,
        )

    if "left_hip" in points and "right_hip" in points:
        items["back_pelvis_slope_deg"] = _slope_deg(
            points["left_hip"],
            points["right_hip"],
            image_width=image_width,
            image_height=image_height,
        )
        items["back_pelvis_height_diff_pct"] = round(
            points["left_hip"]["y"] - points["right_hip"]["y"],
            2,
        )

    if all(k in points for k in ["head_center", "left_hip", "right_hip"]):
        hip_mid = _midpoint(points["left_hip"], points["right_hip"])
        items["head_to_pelvis_center_shift_pct"] = round(
            points["head_center"]["x"] - hip_mid["x"],
            2,
        )

    return _build_result(
        "back",
        items,
        image_width=image_width,
        image_height=image_height,
    )
