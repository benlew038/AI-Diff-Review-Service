from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_invalid_json_returns_400() -> None:
    response = client.post(
        "/v1/reviews",
        headers={"Authorization": "Bearer test-token"},
        content="{not json}",
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_json"


def test_payload_too_large_returns_413() -> None:
    large_diff = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+" + "x" * 1048577
    response = client.post(
        "/v1/reviews",
        headers={"Authorization": "Bearer test-token"},
        json={"diff": large_diff},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"


def test_payload_too_large_due_to_unknown_field_returns_413() -> None:
    # small valid diff, but a very large unknown field in the JSON body
    small_diff = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new"
    large_extra = "x" * 1048577
    response = client.post(
        "/v1/reviews",
        headers={"Authorization": "Bearer test-token"},
        json={"diff": small_diff, "extra": large_extra},
    )
    assert response.status_code == 413
    assert response.json()["error"]["code"] == "payload_too_large"
