"""Unit tests for config validation — no heavy imports."""
import pytest


def test_dev_defaults_allowed():
    from app.config import Settings
    s = Settings(environment="development")
    assert s.is_production is False


def test_production_rejects_missing_jwt_secret():
    from app.config import Settings
    with pytest.raises(ValueError, match="JWT secret key"):
        Settings(environment="production", jwt_secret_key="")


def test_production_rejects_short_jwt_secret():
    from app.config import Settings
    with pytest.raises(ValueError, match="32 characters"):
        Settings(environment="production", jwt_secret_key="short", credential_encryption_key="x")


def test_production_rejects_dev_jwt_secret():
    from app.config import Settings
    with pytest.raises(ValueError, match="JWT secret key"):
        Settings(
            environment="production",
            jwt_secret_key="autogent-dev-secret-change-in-production",
            credential_encryption_key="x",
        )


def test_invalid_environment_rejected():
    from app.config import Settings
    with pytest.raises(ValueError):
        Settings(environment="staging_invalid")


def test_pagination_defaults():
    from app.api.pagination import DEFAULT_LIMIT, MAX_LIMIT
    # pagination_params uses FastAPI Query defaults; just verify constants
    assert DEFAULT_LIMIT == 50
    assert MAX_LIMIT == 200


def test_pagination_custom():
    from app.api.pagination import pagination_params
    params = pagination_params(skip=10, limit=25)
    assert params["skip"] == 10
    assert params["limit"] == 25


def test_paginate_response():
    from app.api.pagination import paginate
    page = paginate([1, 2, 3], total=100, skip=0, limit=3)
    assert page.items == [1, 2, 3]
    assert page.total == 100
    assert page.has_more is True


def test_paginate_no_more():
    from app.api.pagination import paginate
    page = paginate([1, 2, 3], total=3, skip=0, limit=3)
    assert page.has_more is False
