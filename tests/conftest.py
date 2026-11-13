from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND_DIR))

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="custom-n8n-tests-"))
os.environ.setdefault("WORKFLOW_SECRET", "test-secret")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("AI_DISABLED", "1")

from nodes import register_all  # noqa: E402

register_all()
