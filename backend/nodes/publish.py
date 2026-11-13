from __future__ import annotations

import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from engine.registry import register as register_node
from engine.types import Item, NodeContext, NodeDefinition, NodeProperty


def _text_of(report: dict[str, Any]) -> str:
    for key in ("markdown", "shortSummary", "text"):
        value = report.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return json.dumps(report, ensure_ascii=False, indent=2)


def _adf(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text[:30000]}],
            }
        ],
    }


async def _request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: Any = None,
    auth: httpx.Auth | None = None,
    data: Any = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.request(
            method,
            url,
            headers=headers,
            json=json_body,
            auth=auth,
            data=data,
        )
    if response.status_code >= 400:
        raise ValueError(f"{method} {url} -> {response.status_code}: {response.text[:500]}")
    try:
        return response.json()
    except ValueError:
        return {"status": response.status_code, "text": response.text[:2000]}


def _register_publish() -> None:
    async def execute(context: NodeContext) -> dict[str, list[Item]]:
        params = context.params
        report = context.input[0].json if context.input else {}
        if isinstance(report.get("analysis"), dict) and not report.get("markdown"):
            report = {**report, **report["analysis"]}
        text = _text_of(report)
        title = str(params.get("title") or report.get("title") or f"QA report {context.run_id[:8]}")
        channel = str(params.get("channel") or "file")

        credential: dict[str, Any] = {}
        credential_id = params.get("credentialId")
        if credential_id:
            credential = context.credentials.get(str(credential_id))

        if channel == "file":
            configured = str(params.get("path") or "").strip()
            if configured:
                path = Path(configured)
            else:
                data_dir = Path(context.env.get("DATA_DIR") or "data")
                slug = "".join(c if c.isalnum() or c in "-_" else "-" for c in title.lower())[:60]
                stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                path = data_dir / "reports" / f"{stamp}-{slug}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            context.log(f"Отчёт записан: {path}")
            return {"main": [Item(json={"channel": "file", "ok": True, "path": str(path)})]}

        if channel == "slack":
            webhook_url = str(credential.get("webhookUrl") or params.get("webhookUrl") or "")
            if webhook_url:
                result = await _request("POST", webhook_url, json_body={"text": text[:39000]})
            else:
                bot_token = str(credential.get("botToken") or "")
                target = str(params.get("slackChannel") or credential.get("channel") or "")
                if not bot_token or not target:
                    raise ValueError("Slack publish needs webhookUrl or botToken + channel")
                result = await _request(
                    "POST",
                    "https://slack.com/api/chat.postMessage",
                    headers={"Authorization": f"Bearer {bot_token}"},
                    json_body={"channel": target, "text": text[:39000], "mrkdwn": True},
                )
                if not result.get("ok"):
                    raise ValueError(f"Slack API error: {result.get('error')}")
            context.log("Отчёт отправлен в Slack")
            return {"main": [Item(json={"channel": "slack", "ok": True, "details": result})]}

        if channel == "telegram":
            bot_token = str(credential.get("botToken") or "")
            chat_id = str(params.get("chatId") or credential.get("chatId") or "")
            if not bot_token or not chat_id:
                raise ValueError("Telegram publish needs botToken and chatId")
            result = await _request(
                "POST",
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json_body={
                    "chat_id": chat_id,
                    "text": text[:4000],
                    "disable_web_page_preview": True,
                },
            )
            if not result.get("ok"):
                raise ValueError(f"Telegram API error: {result}")
            context.log("Отчёт отправлен в Telegram")
            return {"main": [Item(json={"channel": "telegram", "ok": True, "details": result})]}

        if channel == "confluence":
            base_url = str(credential.get("baseUrl") or "").rstrip("/")
            email = str(credential.get("email") or "")
            token = str(credential.get("apiToken") or "")
            space_key = str(params.get("spaceKey") or credential.get("spaceKey") or "")
            if not base_url or not email or not token or not space_key:
                raise ValueError("Confluence publish needs baseUrl, email, apiToken and spaceKey")
            storage = f"<p>{html.escape(str(report.get('shortSummary') or ''))}</p><pre>{html.escape(text)}</pre>"
            payload: dict[str, Any] = {
                "type": "page",
                "title": title,
                "space": {"key": space_key},
                "body": {"storage": {"value": storage, "representation": "storage"}},
            }
            parent_page_id = str(params.get("parentPageId") or credential.get("parentPageId") or "")
            if parent_page_id:
                payload["ancestors"] = [{"id": parent_page_id}]
            result = await _request(
                "POST",
                f"{base_url}/wiki/rest/api/content",
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                json_body=payload,
                auth=httpx.BasicAuth(email, token),
            )
            page_id = result.get("id")
            url = f"{base_url}/wiki/spaces/{space_key}/pages/{page_id}" if page_id else base_url
            context.log(f"Страница Confluence создана: {url}")
            return {
                "main": [
                    Item(json={"channel": "confluence", "ok": True, "pageId": page_id, "url": url})
                ]
            }

        if channel == "jira":
            base_url = str(credential.get("baseUrl") or "").rstrip("/")
            email = str(credential.get("email") or "")
            token = str(credential.get("apiToken") or "")
            if not base_url or not email or not token:
                raise ValueError("Jira publish needs baseUrl, email and apiToken")
            auth = httpx.BasicAuth(email, token)
            issue_key = str(params.get("issueKey") or "")
            if issue_key:
                result = await _request(
                    "POST",
                    f"{base_url}/rest/api/3/issue/{issue_key}/comment",
                    headers={"Accept": "application/json", "Content-Type": "application/json"},
                    json_body={"body": _adf(text)},
                    auth=auth,
                )
                context.log(f"Комментарий добавлен в {issue_key}")
                return {
                    "main": [
                        Item(json={"channel": "jira", "ok": True, "issueKey": issue_key, "details": result})
                    ]
                }

            project_key = str(params.get("projectKey") or credential.get("projectKey") or "")
            if not project_key:
                raise ValueError("Jira publish needs projectKey (or issueKey for a comment)")
            issue_type = str(params.get("issueType") or credential.get("issueType") or "Task")
            payload = {
                "fields": {
                    "project": {"key": project_key},
                    "summary": title[:250],
                    "description": _adf(text),
                    "issuetype": {"name": issue_type},
                }
            }
            result = await _request(
                "POST",
                f"{base_url}/rest/api/3/issue",
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                json_body=payload,
                auth=auth,
            )
            key = result.get("key")
            context.log(f"Задача Jira создана: {key}")
            return {
                "main": [
                    Item(
                        json={
                            "channel": "jira",
                            "ok": True,
                            "issueKey": key,
                            "url": f"{base_url}/browse/{key}" if key else base_url,
                        }
                    )
                ]
            }

        raise ValueError(f"Unsupported publish channel: {channel}")

    register_node(
        NodeDefinition(
            type="qa.publish",
            display_name="Publish report",
            description="Send the QA report to a file, Slack, Telegram, Confluence or Jira.",
            group="action",
            properties=[
                NodeProperty(
                    name="channel",
                    display_name="Channel",
                    type="options",
                    default="file",
                    options=[
                        {"label": "Local file", "value": "file"},
                        {"label": "Slack", "value": "slack"},
                        {"label": "Telegram", "value": "telegram"},
                        {"label": "Confluence", "value": "confluence"},
                        {"label": "Jira", "value": "jira"},
                    ],
                ),
                NodeProperty(
                    name="credentialId",
                    display_name="Credential",
                    type="credential",
                    credential_type="http",
                    default="",
                ),
                NodeProperty(name="title", display_name="Title", type="string", default=""),
                NodeProperty(name="path", display_name="File path", type="string", default=""),
                NodeProperty(name="slackChannel", display_name="Slack channel", type="string", default=""),
                NodeProperty(name="chatId", display_name="Telegram chat ID", type="string", default=""),
                NodeProperty(name="spaceKey", display_name="Confluence space key", type="string", default=""),
                NodeProperty(name="parentPageId", display_name="Confluence parent page ID", type="string", default=""),
                NodeProperty(name="projectKey", display_name="Jira project key", type="string", default=""),
                NodeProperty(name="issueType", display_name="Jira issue type", type="string", default="Task"),
                NodeProperty(name="issueKey", display_name="Jira issue key (comment)", type="string", default=""),
            ],
            execute=execute,
        )
    )


def register_nodes() -> None:
    _register_publish()
