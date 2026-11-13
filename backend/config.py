from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
ROOT = PROJECT_ROOT


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _resolve_master_secret(data_dir: Path) -> str:
    configured = os.environ.get("WORKFLOW_SECRET", "").strip()
    if configured:
        return configured
    key_file = data_dir / ".master.key"
    data_dir.mkdir(parents=True, exist_ok=True)
    if key_file.exists():
        return key_file.read_text(encoding="utf-8").strip()
    generated = secrets.token_hex(32)
    key_file.write_text(generated, encoding="utf-8")
    try:
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return generated


@dataclass
class Config:
    host: str
    port: int
    data_dir: Path
    ui_dist: Path
    examples_dir: Path
    postman_bin: str
    master_secret: str
    ai_base_url: str
    ai_api_key: str
    ai_model: str
    env: dict[str, str] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "engine.sqlite3"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"


def load_config() -> Config:
    _load_dotenv(PROJECT_ROOT / ".env")
    data_dir = Path(os.environ.get("DATA_DIR", PROJECT_ROOT / "data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "reports").mkdir(parents=True, exist_ok=True)

    ai_base_url = os.environ.get("AI_BASE_URL", "https://api.openai.com/v1")
    ai_api_key = os.environ.get("OPENAI_API_KEY", "")
    ai_model = os.environ.get("AI_MODEL", "gpt-4o-mini")

    env = {key: value for key, value in os.environ.items() if isinstance(value, str)}
    env.setdefault("DATA_DIR", str(data_dir))
    env.setdefault("AI_BASE_URL", ai_base_url)
    env.setdefault("AI_MODEL", ai_model)
    if ai_api_key:
        env.setdefault("OPENAI_API_KEY", ai_api_key)

    return Config(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5678")),
        data_dir=data_dir,
        ui_dist=PROJECT_ROOT / "ui" / "dist",
        examples_dir=PROJECT_ROOT / "examples",
        postman_bin=os.environ.get("POSTMAN_BIN", "postman"),
        master_secret=_resolve_master_secret(data_dir),
        ai_base_url=ai_base_url,
        ai_api_key=ai_api_key,
        ai_model=ai_model,
        env=env,
    )
