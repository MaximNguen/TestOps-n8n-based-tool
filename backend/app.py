from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import nodes
from api.routes import build_router
from config import load_config
from engine.events import EventBus
from engine.executor import Executor
from engine.types import Workflow
from scheduler import Scheduler
from store.db import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("custom-n8n")


class DbCredentials:
    def __init__(self, db: Database) -> None:
        self.db = db

    def get(self, credential_id: str) -> dict[str, Any]:
        credential_type, data = self.db.get_credential_bundle(credential_id)
        return {**data, "__credentialType": credential_type}


def _seed_example(db: Database, examples_dir) -> None:
    if db.count_workflows() > 0:
        return
    path = examples_dir / "qa-pipeline.workflow.json"
    if not path.exists():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    data["id"] = uuid.uuid4().hex
    workflow = Workflow.from_dict(data)
    now = datetime.now(timezone.utc).isoformat()
    workflow.created_at = now
    workflow.updated_at = now
    db.save_workflow(workflow)
    logger.info("Seeded example workflow '%s'", workflow.name)


def create_app() -> FastAPI:
    config = load_config()
    nodes.register_all()

    db = Database(config.db_path, config.master_secret)
    bus = EventBus()
    executor = Executor(
        credentials=DbCredentials(db),
        env=config.env,
        save_run=db.save_run,
        bus=bus,
    )
    scheduler = Scheduler(db, executor)
    _seed_example(db, config.examples_dir)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await scheduler.start()
        logger.info("custom-n8n is listening on http://%s:%s", config.host, config.port)
        try:
            yield
        finally:
            await scheduler.stop()
            db.close()

    app = FastAPI(title="custom-n8n", version="0.1.0", lifespan=lifespan)
    app.state.config = config
    app.state.db = db
    app.state.executor = executor
    app.state.bus = bus
    app.include_router(build_router(db, executor, bus))

    if config.ui_dist.exists():
        app.mount("/", StaticFiles(directory=str(config.ui_dist), html=True), name="ui")
    else:

        @app.get("/", response_class=HTMLResponse)
        async def index() -> str:
            return (
                "<html><body style='font-family:system-ui;padding:40px'>"
                "<h1>custom-n8n</h1>"
                "<p>UI is not built yet. Run:</p>"
                "<pre>cd ui &amp;&amp; npm install &amp;&amp; npm run build</pre>"
                "<p>API: <a href='/docs'>/docs</a> · <a href='/api/nodes'>/api/nodes</a></p>"
                "</body></html>"
            )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    cfg = load_config()
    uvicorn.run("app:app", host=cfg.host, port=cfg.port, reload=True)
