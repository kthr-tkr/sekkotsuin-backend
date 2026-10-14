import io

from httpx import AsyncClient
from PIL import Image

from app.core.config import settings
from tests.conftest import PATIENT


def jpeg_with_gps(width: int = 3000, height: int = 1500) -> bytes:
    """GPS 情報と回転情報（Orientation=6: 90度回転）を持つ JPEG。"""
    img = Image.new("RGB", (width, height), (200, 180, 160))
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation
    exif[0x8825] = {1: "N", 2: (35.0, 41.0, 22.0)}  # GPSInfo
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


async def _assessment(client: AsyncClient, headers: dict[str, str]) -> dict:
    pid = (await client.post("/api/patients", json=PATIENT, headers=headers)).json()["id"]
    res = await client.post("/api/posture-assessments", json={"patient_id": pid}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


async def test_upload_strips_exif_rotates_and_resizes(
    client: AsyncClient, admin_a: dict[str, str]
) -> None:
    a = await _assessment(client, admin_a)
    res = await client.put(
        f"/api/posture-assessments/{a['id']}/images/front",
        files={"file": ("front.jpg", jpeg_with_gps(), "image/jpeg")},
        headers=admin_a,
    )
    assert res.status_code == 200, res.text
    img = res.json()["images"][0]
    assert img["view"] == "front"
    # 90度回転して縦長になり、長辺が 2000px に縮小されている
    assert (img["width"], img["height"]) == (1000, 2000)

    data = (await client.get(img["url"])).content
    saved = Image.open(io.BytesIO(data))
    assert saved.format == "JPEG"
    exif = saved.getexif()
    assert 0x8825 not in exif and 0x0112 not in exif


async def test_replace_and_delete_image(client: AsyncClient, admin_a: dict[str, str]) -> None:
    a = await _assessment(client, admin_a)
    url = f"/api/posture-assessments/{a['id']}/images/back"
    first = await client.put(
        url, files={"file": ("a.jpg", jpeg_with_gps(100, 200), "image/jpeg")}, headers=admin_a
    )
    first_url = first.json()["images"][0]["url"]
    second = await client.put(
        url, files={"file": ("b.jpg", jpeg_with_gps(100, 200), "image/jpeg")}, headers=admin_a
    )
    assert len(second.json()["images"]) == 1
    # 差し替え前のファイルは削除されている
    assert (await client.get(first_url)).status_code == 404

    res = await client.delete(url, headers=admin_a)
    assert res.json()["images"] == []
    assert (await client.delete(url, headers=admin_a)).status_code == 404


async def test_rejects_non_images(client: AsyncClient, admin_a: dict[str, str]) -> None:
    a = await _assessment(client, admin_a)
    url = f"/api/posture-assessments/{a['id']}/images/front"
    res = await client.put(
        url, files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")}, headers=admin_a
    )
    assert res.status_code == 415
    res = await client.put(
        url, files={"file": ("x.jpg", b"not really a jpeg", "image/jpeg")}, headers=admin_a
    )
    assert res.status_code == 422
    big = b"\xff" * (settings.max_upload_bytes + 1)
    res = await client.put(url, files={"file": ("x.jpg", big, "image/jpeg")}, headers=admin_a)
    assert res.status_code == 413
    bad_view = f"/api/posture-assessments/{a['id']}/images/top"
    res = await client.put(
        bad_view, files={"file": ("a.jpg", jpeg_with_gps(10, 10), "image/jpeg")}, headers=admin_a
    )
    assert res.status_code == 422


async def test_update_findings_and_confirm(client: AsyncClient, admin_a: dict[str, str]) -> None:
    a = await _assessment(client, admin_a)
    assert a["findings"]["regions"]["pelvis"] == ""
    body = {
        "title": "初回評価",
        "assessed_at": "2026-10-15T10:00:00+09:00",
        "memo": "右膝痛",
        "findings": {
            "overall_summary": "骨盤の右下制と頭部前方位",
            "important_points": ["頭部前方位", "右肩下制"],
            "regions": {"head_neck": "頭部前方位", "pelvis": "右側が下制"},
        },
    }
    res = await client.put(f"/api/posture-assessments/{a['id']}", json=body, headers=admin_a)
    assert res.status_code == 200, res.text
    assert res.json()["findings"]["regions"]["pelvis"] == "右側が下制"
    assert res.json()["findings"]["regions"]["knee"] == ""

    res = await client.post(f"/api/posture-assessments/{a['id']}/confirm", headers=admin_a)
    assert res.json()["status"] == "confirmed"

    listed = await client.get(
        "/api/posture-assessments", params={"patient_id": a["patient_id"]}, headers=admin_a
    )
    assert listed.json()["total"] == 1


async def test_other_clinic_isolation(
    client: AsyncClient, admin_a: dict[str, str], admin_b: dict[str, str]
) -> None:
    a = await _assessment(client, admin_a)
    res = await client.post(
        "/api/posture-assessments", json={"patient_id": a["patient_id"]}, headers=admin_b
    )
    assert res.status_code == 404
    base = f"/api/posture-assessments/{a['id']}"
    assert (await client.get(base, headers=admin_b)).status_code == 404
    res = await client.put(
        f"{base}/images/front",
        files={"file": ("a.jpg", jpeg_with_gps(10, 10), "image/jpeg")},
        headers=admin_b,
    )
    assert res.status_code == 404
    assert (await client.post(f"{base}/confirm", headers=admin_b)).status_code == 404
    assert (await client.get("/api/posture-assessments", headers=admin_b)).json()["total"] == 0
