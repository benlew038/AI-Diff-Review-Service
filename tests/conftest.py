import pytest

from app.application.services.review_service import default_review_service


@pytest.fixture(autouse=True)
def reset_service_state() -> None:
    default_review_service.reset()
