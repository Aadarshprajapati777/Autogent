"""Unit tests for webhook signature verification — lightweight, no app import."""
import hashlib
import hmac
from unittest.mock import patch, MagicMock


def test_github_webhook_valid_signature():
    from app.api.v1.github_webhooks import _verify
    secret = "test-secret"
    payload = b'{"test": true}'
    sig = "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    with patch("app.api.v1.github_webhooks.settings") as mock_settings:
        mock_settings.github_webhook_secret = secret
        mock_settings.is_production = False
        assert _verify(payload, sig) is True


def test_github_webhook_invalid_signature():
    from app.api.v1.github_webhooks import _verify
    with patch("app.api.v1.github_webhooks.settings") as mock_settings:
        mock_settings.github_webhook_secret = "real-secret"
        mock_settings.is_production = False
        assert _verify(b'{"test": true}', "sha256=invalid") is False


def test_github_webhook_missing_secret_rejected_in_production():
    from app.api.v1.github_webhooks import _verify
    with patch("app.api.v1.github_webhooks.settings") as mock_settings:
        mock_settings.github_webhook_secret = ""
        mock_settings.is_production = True
        assert _verify(b'{"test": true}', "") is False


def test_github_webhook_missing_secret_allowed_in_dev():
    from app.api.v1.github_webhooks import _verify
    with patch("app.api.v1.github_webhooks.settings") as mock_settings:
        mock_settings.github_webhook_secret = ""
        mock_settings.is_production = False
        assert _verify(b'{"test": true}', "") is True
