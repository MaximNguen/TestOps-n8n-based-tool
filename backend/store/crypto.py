from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken


class SecretBox:
    def __init__(self, secret: str) -> None:
        digest = hashlib.sha256(secret.encode("utf-8")).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(digest))

    def encrypt(self, data: dict[str, Any]) -> str:
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._fernet.encrypt(payload).decode("ascii")

    def decrypt(self, token: str) -> dict[str, Any]:
        try:
            raw = self._fernet.decrypt(token.encode("ascii"))
        except InvalidToken as error:
            raise ValueError(
                "Cannot decrypt credential: master key changed or credential is corrupted"
            ) from error
        return json.loads(raw.decode("utf-8"))
