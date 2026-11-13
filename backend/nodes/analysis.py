from __future__ import annotations

import re
from collections import Counter
from typing import Any
from urllib.parse import urlsplit


def endpoint_of(test: dict[str, Any]) -> str:
    method = str(test.get("method") or "").upper()
    url = str(test.get("url") or test.get("path") or "")
    path = urlsplit(url).path if "://" in url else url
    path = re.sub(r"/\d+(?=/|$)", "/{id}", path)
    path = re.sub(r"/[0-9a-f]{8,}(?=/|$)", "/{id}", path)
    return f"{method} {path}".strip()


def build_summary(tests: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(tests)
    passed = sum(1 for test in tests if test.get("passed"))
    failed = sum(1 for test in tests if not test.get("passed") and not test.get("skipped"))
    skipped = sum(1 for test in tests if test.get("skipped"))
    return {
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "passRate": round((passed / total) * 100, 1) if total else 0.0,
    }


def _error_text(test: dict[str, Any]) -> str:
    parts: list[str] = []
    if test.get("error"):
        parts.append(str(test["error"]))
    for assertion in test.get("assertions") or []:
        if isinstance(assertion, dict) and assertion.get("error"):
            parts.append(str(assertion["error"]))
    return " | ".join(parts)


def classify(test: dict[str, Any]) -> dict[str, Any]:
    status = test.get("status")
    try:
        status_code = int(status) if status is not None else None
    except (TypeError, ValueError):
        status_code = None
    error = _error_text(test).lower()
    endpoint = endpoint_of(test)

    area = "Не классифицировано"
    cause = "Причина неочевидна, нужен разбор лога"
    recommendation = "Открыть отчёт по тесту и проверить запрос/ответ вручную"
    confidence = "low"

    if any(token in error for token in ("econnrefused", "enotfound", "getaddrinfo", "connection refused")):
        area = "Окружение / инфраструктура"
        cause = "Сервис недоступен по адресу из baseUrl (не запущен, неверный хост/порт)"
        recommendation = "Проверить, что стенд поднят, DNS/порт доступны из раннера"
        confidence = "high"
    elif any(token in error for token in ("timeout", "etimedout", "timed out", "socket hang up")):
        area = "Окружение / производительность"
        cause = "Таймаут запроса: медленный ответ, перегрузка или блокировка сетью"
        recommendation = "Проверить latency и лимиты, увеличить timeout только после диагностики"
        confidence = "high"
    elif status_code is not None and 500 <= status_code < 600:
        area = "Бэкенд / сервис"
        cause = f"Сервер вернул {status_code}: ошибка внутри сервиса или зависимости"
        recommendation = "Смотреть логи сервиса по traceId/времени, искать упавший downstream"
        confidence = "high"
    elif status_code in (401, 403):
        area = "Авторизация / доступы"
        cause = f"Ответ {status_code}: невалидный/просроченный токен или не хватает роли"
        recommendation = "Обновить креды, проверить scopes/роли тестового пользователя"
        confidence = "high"
    elif status_code == 404:
        area = "Контракт / маршрутизация"
        cause = "404: неверный путь, версия API или baseUrl"
        recommendation = "Сверить путь с OpenAPI и настройкой baseUrl окружения"
        confidence = "high"
    elif status_code in (405, 415):
        area = "Контракт / маршрутизация"
        cause = f"Ответ {status_code}: неверный HTTP-метод или Content-Type"
        recommendation = "Проверить метод и заголовки в тест-кейсе"
        confidence = "high"
    elif status_code == 429:
        area = "Лимиты / тестовые данные"
        cause = "429: сработал rate limit"
        recommendation = "Добавить задержку/backoff или изолированные тестовые данные"
        confidence = "high"
    elif status_code in (400, 409, 422):
        area = "Данные / валидация"
        cause = f"Ответ {status_code}: запрос не прошёл валидацию или конфликтует с состоянием"
        recommendation = "Проверить тело запроса, обязательные поля и предусловия теста"
        confidence = "medium"
    elif any(
        token in error
        for token in (
            "schema",
            "required",
            "expected",
            "json",
            "typeerror",
            "assertionerror",
            "to equal",
            "deep equal",
        )
    ):
        area = "Контракт API (drift)"
        cause = "Ответ не совпал с ожиданиями/схемой — вероятен drift контракта или устаревший кейс"
        recommendation = "Сравнить фактический ответ с OpenAPI-схемой и обновить контракт/кейс"
        confidence = "medium"
    elif status_code is not None and 200 <= status_code < 300:
        area = "Ожидания теста"
        cause = "HTTP-статус успешный, но проверки не прошли — скорее всего устаревшие ожидания"
        recommendation = "Пересмотреть ассерты и тестовые данные"
        confidence = "medium"

    return {
        "endpoint": endpoint,
        "test": test.get("name") or endpoint,
        "area": area,
        "cause": cause,
        "recommendation": recommendation,
        "confidence": confidence,
        "status": status_code,
        "error": _error_text(test)[:300],
    }


def analyze(tests: list[dict[str, Any]], max_failures_per_area: int = 3) -> dict[str, Any]:
    summary = build_summary(tests)
    failures = [test for test in tests if not test.get("passed") and not test.get("skipped")]
    classified = [classify(test) for test in failures]

    groups: dict[str, list[dict[str, Any]]] = {}
    for item in classified:
        groups.setdefault(item["area"], []).append(item)

    likely_problems: list[dict[str, Any]] = []
    for area, items in sorted(groups.items(), key=lambda pair: len(pair[1]), reverse=True):
        share = round((len(items) / len(failures)) * 100, 1) if failures else 0.0
        causes = Counter(item["cause"] for item in items)
        top_cause = causes.most_common(1)[0][0]
        confidence = "high" if share >= 50 else "medium" if share >= 25 else "low"
        likely_problems.append(
            {
                "area": area,
                "cause": top_cause,
                "confidence": confidence,
                "failureCount": len(items),
                "share": share,
                "evidence": [
                    {
                        "test": item["test"],
                        "endpoint": item["endpoint"],
                        "status": item["status"],
                        "error": item["error"],
                    }
                    for item in items[:max_failures_per_area]
                ],
                "recommendations": sorted({item["recommendation"] for item in items}),
            }
        )

    endpoint_counter = Counter(item["endpoint"] for item in classified)
    top_endpoints = [
        {"endpoint": endpoint, "failures": count}
        for endpoint, count in endpoint_counter.most_common(10)
    ]

    recommendations: list[str] = []
    for problem in likely_problems:
        recommendations.extend(problem["recommendations"][:1])

    if failures:
        short_summary = (
            f"Провалено {summary['failed']} из {summary['total']} тестов "
            f"({100 - summary['passRate']:.1f}%). Основная зона риска: "
            f"{likely_problems[0]['area']} — {likely_problems[0]['cause']}."
        )
    else:
        short_summary = f"Все {summary['total']} тестов прошли (pass rate {summary['passRate']}%)."

    return {
        "summary": summary,
        "shortSummary": short_summary,
        "topFailingEndpoints": top_endpoints,
        "likelyProblems": likely_problems,
        "recommendations": list(dict.fromkeys(recommendations)),
    }
