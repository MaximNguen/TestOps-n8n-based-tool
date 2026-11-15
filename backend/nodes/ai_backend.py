from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from engine.types import NodeContext

from .ai_client import _extract_json, chat_completion, chat_json

OPENCODE_DEFAULT_TIMEOUT = 180.0


@dataclass
class AiSettings:
    provider: str
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    opencode_bin: str = "opencode"
    agent: str = ""
    cwd: str | None = None
    allow_tools: bool = False
    timeout: float = OPENCODE_DEFAULT_TIMEOUT


def resolve_ai_settings(context: NodeContext) -> AiSettings:
    credential: dict[str, Any] = {}
    credential_type = ""
    credential_id = context.params.get("credentialId")
    if credential_id:
        credential = dict(context.credentials.get(str(credential_id)))
        credential_type = str(credential.pop("__credentialType", ""))

    provider = str(context.params.get("provider") or "auto")
    if provider == "auto":
        if credential_type == "opencode":
            provider = "opencode"
        elif credential_type == "deepseek":
            provider = "deepseek"
        elif credential_type == "anthropic":
            provider = "anthropic"
        elif context.env.get("OPENCODE_BIN"):
            provider = "opencode"
        elif context.env.get("DEEPSEEK_API_KEY"):
            provider = "deepseek"
        elif context.env.get("ANTHROPIC_API_KEY"):
            provider = "anthropic"
        else:
            provider = "openai"

    if provider == "anthropic":
        return AiSettings(
            provider="anthropic",
            base_url=str(
                context.params.get("baseUrl")
                or credential.get("baseUrl")
                or context.env.get("ANTHROPIC_BASE_URL")
                or "https://api.anthropic.com"
            ),
            api_key=str(
                credential.get("apiKey") or context.env.get("ANTHROPIC_API_KEY") or ""
            ),
            model=str(
                context.params.get("model")
                or credential.get("model")
                or context.env.get("ANTHROPIC_MODEL")
                or "claude-sonnet-4-5"
            ),
            timeout=float(context.params.get("timeoutSeconds") or 90),
        )

    if provider == "deepseek":
        return AiSettings(
            provider="deepseek",
            base_url=str(
                context.params.get("baseUrl")
                or credential.get("baseUrl")
                or context.env.get("DEEPSEEK_BASE_URL")
                or "https://api.deepseek.com"
            ),
            api_key=str(
                credential.get("apiKey") or context.env.get("DEEPSEEK_API_KEY") or ""
            ),
            model=str(
                context.params.get("model")
                or credential.get("model")
                or context.env.get("DEEPSEEK_MODEL")
                or "deepseek-flash"
            ),
            timeout=float(context.params.get("timeoutSeconds") or 90),
        )

    if provider == "opencode":
        cwd = str(
            context.params.get("cwd")
            or credential.get("cwd")
            or context.env.get("OPENCODE_CWD")
            or ""
        ).strip()
        allow_tools = bool(
            context.params.get("allowTools")
            or credential.get("allowTools")
            or str(context.env.get("OPENCODE_ALLOW_TOOLS") or "").lower()
            in ("1", "true", "yes", "on")
        )
        return AiSettings(
            provider="opencode",
            model=str(
                context.params.get("model")
                or credential.get("model")
                or context.env.get("OPENCODE_MODEL")
                or ""
            ),
            opencode_bin=str(
                context.params.get("opencodeBin")
                or credential.get("bin")
                or context.env.get("OPENCODE_BIN")
                or "opencode"
            ),
            agent=str(
                context.params.get("agent")
                or credential.get("agent")
                or context.env.get("OPENCODE_AGENT")
                or ""
            ),
            cwd=cwd or None,
            allow_tools=allow_tools,
            timeout=float(
                context.params.get("timeoutSeconds")
                or credential.get("timeoutSeconds")
                or OPENCODE_DEFAULT_TIMEOUT
            ),
        )

    return AiSettings(
        provider="openai",
        base_url=str(
            context.params.get("baseUrl")
            or credential.get("baseUrl")
            or context.env.get("AI_BASE_URL")
            or context.env.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ),
        api_key=str(credential.get("apiKey") or context.env.get("OPENAI_API_KEY") or ""),
        model=str(
            context.params.get("model")
            or credential.get("model")
            or context.env.get("AI_MODEL")
            or context.env.get("OPENAI_MODEL")
            or "gpt-4o-mini"
        ),
        timeout=float(context.params.get("timeoutSeconds") or 90),
    )


def _messages_to_prompt(
    messages: list[dict[str, str]],
    allow_tools: bool = False,
) -> str:
    system = "\n\n".join(
        message.get("content", "") for message in messages if message.get("role") == "system"
    )
    user = "\n\n".join(
        message.get("content", "") for message in messages if message.get("role") != "system"
    )
    instructions = (
        "You may use tools to inspect files in the working directory. "
        "Base your answer on the actual files and do not modify them."
        if allow_tools
        else "Answer directly. Do not use tools and do not modify files."
    )
    parts = [instruction for instruction in (instructions, system, user) if instruction.strip()]
    return "\n\n".join(parts)


def _merge_chunks(chunks: list[str]) -> str:
    merged = ""
    for chunk in chunks:
        if not chunk:
            continue
        if chunk.startswith(merged):
            merged = chunk
        elif merged.endswith(chunk):
            continue
        else:
            merged = f"{merged}\n{chunk}" if merged else chunk
    return merged.strip()


def _parse_opencode_events(stdout: str) -> tuple[str, list[str]]:
    chunks: list[str] = []
    errors: list[str] = []
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "error":
            error = event.get("error") or {}
            data = error.get("data") if isinstance(error, dict) else {}
            message = (
                (data or {}).get("message")
                or (error.get("message") if isinstance(error, dict) else None)
                or (error.get("name") if isinstance(error, dict) else None)
                or json.dumps(error, default=str)[:500]
            )
            errors.append(str(message))
        part = event.get("part")
        if not isinstance(part, dict):
            properties = event.get("properties")
            part = properties.get("part") if isinstance(properties, dict) else None
        if isinstance(part, dict) and part.get("type") == "text":
            text = part.get("text")
            if isinstance(text, str) and text:
                chunks.append(text)
    return _merge_chunks(chunks), errors


def _resolve_binary(binary: str) -> str:
    resolved = shutil.which(binary)
    if not resolved:
        raise ValueError(
            f"opencode binary not found ({binary}). Install opencode or set OPENCODE_BIN / opencodeBin."
        )
    if os.name == "nt" and resolved.lower().endswith((".cmd", ".bat")):
        try:
            content = Path(resolved).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            content = ""
        match = re.search(r'"([^"]+\.exe)"', content, re.IGNORECASE)
        if match:
            candidate = match.group(1).replace("%dp0%", str(Path(resolved).parent))
            candidate = os.path.expandvars(candidate)
            if Path(candidate).is_file():
                return candidate
    return resolved


async def opencode_run(settings: AiSettings, messages: list[dict[str, str]]) -> str:
    binary = _resolve_binary(settings.opencode_bin)
    prompt = _messages_to_prompt(messages, allow_tools=settings.allow_tools)

    descriptor, temp_name = tempfile.mkstemp(prefix="opencode-prompt-", suffix=".md")
    temp_path = Path(temp_name)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(prompt)

    arguments = ["run", "--format", "json"]
    if settings.model:
        arguments.extend(["--model", settings.model])
    if settings.agent:
        arguments.extend(["--agent", settings.agent])
    if settings.allow_tools:
        arguments.append("--auto")
    arguments.extend(
        [
            "Follow the instructions in the attached file exactly. "
            + (
                "Use tools to inspect files if needed and do not modify them."
                if settings.allow_tools
                else "Answer directly and do not modify files."
            ),
            "--file",
            str(temp_path),
        ]
    )

    if os.name == "nt" and binary.lower().endswith((".cmd", ".bat")):
        command = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", binary, *arguments]
    else:
        command = [binary, *arguments]

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=settings.cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=settings.timeout
            )
        except asyncio.TimeoutError as error:
            process.kill()
            await process.wait()
            raise ValueError(f"opencode timed out after {settings.timeout} seconds") from error
        except asyncio.CancelledError:
            process.kill()
            await process.wait()
            raise
    except FileNotFoundError as error:
        raise ValueError(f"opencode could not start: {error}") from error
    finally:
        temp_path.unlink(missing_ok=True)

    text, errors = _parse_opencode_events(stdout.decode("utf-8", "replace"))
    if errors:
        raise ValueError(f"opencode error: {'; '.join(errors)}")

    if not text:
        stderr_text = stderr.decode("utf-8", "replace").strip()
        stdout_text = stdout.decode("utf-8", "replace").strip()
        detail = stderr_text[-1500:] or stdout_text[-1500:] or "no output"
        raise ValueError(f"opencode returned no text (exit {process.returncode}): {detail}")

    return text


async def _anthropic_chat(
    settings: AiSettings,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 8192,
) -> str:
    system = "\n\n".join(
        message.get("content", "") for message in messages if message.get("role") == "system"
    )
    chat_messages = [
        {"role": message["role"], "content": message.get("content", "")}
        for message in messages
        if message.get("role") in ("user", "assistant")
    ]
    payload: dict[str, Any] = {
        "model": settings.model,
        "max_tokens": max_tokens,
        "messages": chat_messages,
    }
    if system.strip():
        payload["system"] = system
    if temperature is not None:
        payload["temperature"] = temperature

    headers = {
        "x-api-key": settings.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    url = settings.base_url.rstrip("/") + "/v1/messages"
    async with httpx.AsyncClient(timeout=settings.timeout) as client:
        response = await client.post(url, headers=headers, json=payload)
    if response.status_code >= 400:
        raise ValueError(
            f"Anthropic request failed ({response.status_code}): {response.text[:500]}"
        )
    data = response.json()
    text = "\n".join(
        part.get("text", "")
        for part in (data.get("content") or [])
        if isinstance(part, dict) and part.get("type") == "text"
    ).strip()
    if not text:
        raise ValueError(f"Anthropic returned no text: {str(data)[:500]}")
    return text


async def ask_text(
    settings: AiSettings,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    json_mode: bool = False,
) -> str:
    if settings.provider == "opencode":
        return await opencode_run(settings, messages)
    if settings.provider == "anthropic":
        return await _anthropic_chat(settings, messages, temperature=temperature)
    return await chat_completion(
        base_url=settings.base_url,
        api_key=settings.api_key,
        model=settings.model,
        messages=messages,
        temperature=temperature,
        json_mode=json_mode,
        timeout=settings.timeout,
    )


async def ask_json(
    settings: AiSettings,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
) -> Any:
    if settings.provider == "opencode":
        return _extract_json(await opencode_run(settings, messages))
    if settings.provider == "anthropic":
        return _extract_json(await _anthropic_chat(settings, messages, temperature=temperature))
    return await chat_json(
        base_url=settings.base_url,
        api_key=settings.api_key,
        model=settings.model,
        messages=messages,
        temperature=temperature,
        timeout=settings.timeout,
    )
