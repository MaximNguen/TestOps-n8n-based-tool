from __future__ import annotations

import json
from typing import Any

from engine.registry import register as register_node
from engine.types import Item, NodeContext, NodeDefinition, NodeProperty

from .ai_backend import ask_json, ask_text, resolve_ai_settings
from .analysis import analyze
from .triggers import normalize_tests


def _provider_properties() -> list[NodeProperty]:
    return [
        NodeProperty(
            name="provider",
            display_name="Provider",
            type="options",
            default="auto",
            options=[
                {"label": "Auto (opencode, then DeepSeek, then OpenAI)", "value": "auto"},
                {"label": "opencode CLI (local auth)", "value": "opencode"},
                {"label": "DeepSeek API (API key)", "value": "deepseek"},
                {"label": "Anthropic Claude API (API key)", "value": "anthropic"},
                {"label": "OpenAI-compatible API (GPT, local)", "value": "openai"},
            ],
            description=(
                "opencode uses the local 'opencode run' CLI and your existing login/models. "
                "DeepSeek uses api.deepseek.com. Anthropic uses api.anthropic.com/v1/messages. "
                "OpenAI provider works with GPT and any OpenAI-compatible endpoint."
            ),
        ),
        NodeProperty(
            name="credentialId",
            display_name="AI credential",
            type="credential",
            credential_type="ai",
            default="",
        ),
        NodeProperty(
            name="baseUrl",
            display_name="OpenAI base URL",
            type="string",
            default="",
            description="Only for the OpenAI-compatible provider.",
        ),
        NodeProperty(
            name="model",
            display_name="Model",
            type="string",
            default="",
            description="For opencode: provider/model, e.g. opencode/deepseek-v4.1-flash-free.",
        ),
        NodeProperty(
            name="agent",
            display_name="opencode agent",
            type="string",
            default="",
            description="Optional opencode agent name (e.g. build).",
        ),
        NodeProperty(
            name="opencodeBin",
            display_name="opencode binary",
            type="string",
            default="",
            description="Defaults to OPENCODE_BIN or 'opencode'.",
        ),
    ]


def _register_agent() -> None:
    async def execute(context: NodeContext) -> dict[str, list[Item]]:
        if context.env.get("AI_DISABLED") == "1":
            raise ValueError("AI is disabled by AI_DISABLED=1")
        settings = resolve_ai_settings(context)
        if settings.provider != "opencode" and not settings.api_key:
            raise ValueError(
                "AI node requires a credential or DEEPSEEK_API_KEY / OPENAI_API_KEY"
            )
        system_prompt = str(context.params.get("systemPrompt") or "You are a helpful QA assistant.")
        user_prompt = str(context.params.get("prompt") or "")
        if context.input:
            payload = json.dumps([item.json for item in context.input[:20]], ensure_ascii=False)
            user_prompt = f"{user_prompt}\n\nInput data:\n{payload}"
        json_mode = str(context.params.get("responseFormat") or "text") == "json"
        if json_mode:
            system_prompt = f"{system_prompt}\nReturn only valid JSON."
        content = await ask_text(
            settings,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=float(context.params.get("temperature") or 0.2),
            json_mode=json_mode,
        )
        context.log(f"AI response received via {settings.provider} ({len(content)} chars)")
        if json_mode:
            from .ai_client import _extract_json

            return {
                "main": [
                    Item(json={"json": _extract_json(content), "provider": settings.provider})
                ]
            }
        return {"main": [Item(json={"text": content, "provider": settings.provider})]}

    register_node(
        NodeDefinition(
            type="ai.agent",
            display_name="AI agent (LLM)",
            description=(
                "Call a model with a prompt and upstream data. Uses opencode CLI or any "
                "OpenAI-compatible API."
            ),
            group="qa",
            properties=[
                *_provider_properties(),
                NodeProperty(
                    name="systemPrompt",
                    display_name="System prompt",
                    type="text",
                    default="You are a senior QA engineer.",
                    rows=3,
                ),
                NodeProperty(
                    name="prompt",
                    display_name="Prompt",
                    type="text",
                    default="Analyze the input and answer briefly.",
                    rows=5,
                ),
                NodeProperty(
                    name="responseFormat",
                    display_name="Response format",
                    type="options",
                    default="text",
                    options=[
                        {"label": "Text", "value": "text"},
                        {"label": "JSON", "value": "json"},
                    ],
                ),
                NodeProperty(name="temperature", display_name="Temperature", type="number", default=0.2),
                NodeProperty(
                    name="cwd",
                    display_name="Working directory",
                    type="string",
                    default="",
                    description="opencode working directory. Set the project path for code review.",
                ),
                NodeProperty(
                    name="allowTools",
                    display_name="Allow tools",
                    type="boolean",
                    default=False,
                    description=(
                        "Let opencode inspect files via tools (adds --auto). "
                        "Use a read-only agent such as plan."
                    ),
                ),
            ],
            execute=execute,
        )
    )


def _register_summarize_results() -> None:
    async def execute(context: NodeContext) -> dict[str, list[Item]]:
        payload = context.input[0].json if context.input else {}
        tests = payload.get("tests")
        if not isinstance(tests, list):
            nested = payload.get("analysis") if isinstance(payload.get("analysis"), dict) else {}
            tests = nested.get("tests") or []
        if not tests:
            normalized, _ = normalize_tests(payload, "generic")
            tests = normalized

        heuristic = analyze(tests)
        result: dict[str, Any] = {
            **heuristic,
            "tests": tests[:300],
            "source": payload.get("source") or "unknown",
            "aiUsed": False,
        }

        use_ai = bool(context.params.get("useAi", True)) and context.env.get("AI_DISABLED") != "1"
        if use_ai:
            settings = resolve_ai_settings(context)
            ai_available = settings.provider == "opencode" or bool(settings.api_key)
            if settings.provider == "deepseek":
                ai_available = bool(settings.api_key)
            if ai_available:
                language = str(context.params.get("language") or "ru")
                digest = {
                    "summary": heuristic["summary"],
                    "topFailingEndpoints": heuristic["topFailingEndpoints"],
                    "likelyProblems": [
                        {
                            "area": problem["area"],
                            "cause": problem["cause"],
                            "failureCount": problem["failureCount"],
                        }
                        for problem in heuristic["likelyProblems"]
                    ],
                    "failures": [
                        {
                            "name": test.get("name"),
                            "url": test.get("url"),
                            "status": test.get("status"),
                            "error": test.get("error"),
                        }
                        for test in tests
                        if not test.get("passed")
                    ][:25],
                }
                try:
                    ai_result = await ask_json(
                        settings,
                        [
                            {
                                "role": "system",
                                "content": (
                                    "Ты QA-лид. По результатам автотестов дай краткое резюме "
                                    f"на языке '{language}'. Верни ТОЛЬКО JSON: "
                                    '{"shortSummary": string, '
                                    '"likelyProblems": [{"area": string, "cause": string, '
                                    '"confidence": "high|medium|low", "evidence": [string]}], '
                                    '"recommendations": [string]}. '
                                    "Пиши конкретно: где скорее всего проблема и что проверить первым. "
                                    "Не обсуждай структуру входного JSON и counts, давай выводы по существу."
                                ),
                            },
                            {"role": "user", "content": json.dumps(digest, ensure_ascii=False)},
                        ],
                    )
                    if isinstance(ai_result, dict):
                        if isinstance(ai_result.get("shortSummary"), str):
                            result["shortSummary"] = ai_result["shortSummary"]
                        ai_problems = ai_result.get("likelyProblems")
                        if isinstance(ai_problems, list) and ai_problems:
                            insights = []
                            for problem in ai_problems:
                                if not isinstance(problem, dict):
                                    continue
                                evidence = [
                                    str(entry)
                                    for entry in (problem.get("evidence") or [])[:5]
                                    if entry
                                ]
                                insights.append(
                                    {
                                        "area": problem.get("area") or "AI-гипотеза",
                                        "cause": problem.get("cause") or "",
                                        "confidence": problem.get("confidence") or "low",
                                        "evidence": evidence,
                                    }
                                )
                            if insights:
                                result["aiInsights"] = insights
                        ai_recommendations = ai_result.get("recommendations")
                        if isinstance(ai_recommendations, list):
                            result["recommendations"] = list(
                                dict.fromkeys(
                                    [
                                        *(heuristic.get("recommendations") or []),
                                        *[str(entry) for entry in ai_recommendations if entry],
                                    ]
                                )
                            )
                        result["aiUsed"] = True
                        result["aiProvider"] = settings.provider
                        context.log(f"AI-резюме добавлено ({settings.provider})")
                except Exception as error:  # noqa: BLE001
                    context.log(f"AI недоступен: {error}", "error")
                    raise
            else:
                result["aiNote"] = (
                    "AI отключён или провайдер не настроен — использована эвристика"
                )

        result["analysis"] = {
            key: value
            for key, value in result.items()
            if key not in ("analysis", "tests")
        }
        context.log(result.get("shortSummary") or "Анализ результатов готов")
        return {"main": [Item(json=result)]}

    register_node(
        NodeDefinition(
            type="ai.summarizeResults",
            display_name="Summarize test results",
            description=(
                "Build a short summary of autotest results and point to likely problem areas. "
                "Works offline (heuristics), opencode or an OpenAI-compatible LLM."
            ),
            group="qa",
            properties=[
                NodeProperty(
                    name="useAi",
                    display_name="Use AI",
                    type="boolean",
                    default=True,
                    description="Falls back to heuristics when no provider is configured.",
                ),
                NodeProperty(
                    name="language",
                    display_name="Summary language",
                    type="options",
                    default="ru",
                    options=[
                        {"label": "Russian", "value": "ru"},
                        {"label": "English", "value": "en"},
                    ],
                ),
                *_provider_properties(),
            ],
            execute=execute,
        )
    )


def register_nodes() -> None:
    _register_agent()
    _register_summarize_results()
