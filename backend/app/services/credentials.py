from cryptography.fernet import Fernet, InvalidToken
from ..config import settings


class CredentialVault:
    def _fernet(self) -> Fernet:
        if not settings.credential_encryption_key:
            raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY is required")
        return Fernet(settings.credential_encryption_key.encode())

    def encrypt(self, value: str) -> str:
        return self._fernet().encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet().decrypt(value.encode()).decode()
        except InvalidToken as error:
            raise RuntimeError("Stored credential cannot be decrypted") from error


vault = CredentialVault()
