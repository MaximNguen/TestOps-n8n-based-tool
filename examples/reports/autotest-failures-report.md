# QA report: autotest results

> Прогон в основном красный: 6 из 7 тестов упали (passRate 14.3%). Провалы разбросаны по разным причинам, но две из них — авторизация/роли (401 на логине и 403 на DELETE /users) — выглядят как проблема тестовых данных и токенов, а не продукта. Отдельно требуют внимания 500 на GET /users, таймаут POST /payments и расхождение схемы GET /products (нет поля 'price'). 404 на GET /orders/42 больше похоже на отсутствующие тестовые данные или неверный путь, чем на баг сервиса.

> AI analysis: opencode

## Summary

| Metric | Value |
| --- | --- |
| Total | 7 |
| Passed | 1 |
| Failed | 6 |
| Skipped | 0 |
| Pass rate | 14.3% |

## Likely problems

### Авторизация / доступы — medium confidence (2 failures)

**Cause:** Ответ 401: невалидный/просроченный токен или не хватает роли

**Evidence:**
- `POST /auth/login` / POST /auth/login (status 401): Unauthorized: token expired
- `DELETE /users/{id}` / DELETE /users/99 (status 403): Forbidden: role user cannot delete users

### Бэкенд / сервис — low confidence (1 failures)

**Cause:** Сервер вернул 500: ошибка внутри сервиса или зависимости

**Evidence:**
- `GET /users` / GET /users (status 500): Internal Server Error

### Контракт / маршрутизация — low confidence (1 failures)

**Cause:** 404: неверный путь, версия API или baseUrl

**Evidence:**
- `GET /orders/{id}` / GET /orders/42 (status 404): Not Found

### Окружение / производительность — low confidence (1 failures)

**Cause:** Таймаут запроса: медленный ответ, перегрузка или блокировка сетью

**Evidence:**
- `POST /payments` / POST /payments (status None): ETIMEDOUT: request timed out after 30000ms

### Контракт API (drift) — low confidence (1 failures)

**Cause:** Ответ не совпал с ожиданиями/схемой — вероятен drift контракта или устаревший кейс

**Evidence:**
- `GET /products` / GET /products (status 200): Schema mismatch: required field 'price' is missing

## AI hypotheses

### Авторизация / тестовые креды — high confidence

**Cause:** POST /auth/login возвращает 401 'token expired' — тест ходит со просроченным/захардкоженным токеном либо использует устаревшие креды; вероятно, отсюда же каскад по защищённым эндпоинтам

- POST /auth/login → 401 Unauthorized: token expired
- 1 passed из 7 — большинство защищённых вызовов падают на доступе

### Авторизация / RBAC — high confidence

**Cause:** DELETE /users/99 выполняется под ролью 'user' — не хватает прав администратора; тест использует не тот токен/роль

- DELETE /users/99 → 403 Forbidden: role user cannot delete users

### Бэкенд / зависимости — medium confidence

**Cause:** GET /users отдаёт 500 — ошибка внутри сервиса или его зависимости (БД/внешний вызов); нужно смотреть серверные логи и трейсы

- GET /users → 500 Internal Server Error

### Платёжный сервис / производительность — medium confidence

**Cause:** POST /payments не уложился в 30с — синхронный вызов внешнего провайдера завис, либо перегрузка/блокировка сети; таймаут не продуктовый симптом, а следствие

- POST /payments → ETIMEDOUT: request timed out after 30000ms
- status = null, запрос не получил ответа вовсе

### Контракт API (drift) — high confidence

**Cause:** GET /products вернул 200, но без обязательного 'price' — поле переименовано/убрано на бэке или схема в тесте устарела; тест ловит реальный drift, не сетевую ошибку

- GET /products → 200 OK, Schema mismatch: required field 'price' is missing

### Тестовые данные / маршрутизация — medium confidence

**Cause:** GET /orders/42 → 404: заказ 42 отсутствует в тестовом окружении либо неверный путь/версия API/baseUrl

- GET /orders/42 → 404 Not Found
- запрос дошёл до api.demo.local, т.е. хост резолвится

## Top failing endpoints

| Endpoint | Failures |
| --- | --- |
| `GET /users` | 1 |
| `POST /auth/login` | 1 |
| `GET /orders/{id}` | 1 |
| `POST /payments` | 1 |
| `GET /products` | 1 |
| `DELETE /users/{id}` | 1 |

## Failed tests

| Test | Endpoint | Status | Error |
| --- | --- | --- | --- |
| GET /users | `https://api.demo.local/users` | 500 | Internal Server Error |
| POST /auth/login | `https://api.demo.local/auth/login` | 401 | Unauthorized: token expired |
| GET /orders/42 | `https://api.demo.local/orders/42` | 404 | Not Found |
| POST /payments | `https://api.demo.local/payments` | — | ETIMEDOUT: request timed out after 30000ms |
| GET /products | `https://api.demo.local/products` | 200 | Schema mismatch: required field 'price' is missing |
| DELETE /users/99 | `https://api.demo.local/users/99` | 403 | Forbidden: role user cannot delete users |

## Recommendations

- Обновить креды, проверить scopes/роли тестового пользователя
- Смотреть логи сервиса по traceId/времени, искать упавший downstream
- Сверить путь с OpenAPI и настройкой baseUrl окружения
- Проверить latency и лимиты, увеличить timeout только после диагностики
- Сравнить фактический ответ с OpenAPI-схемой и обновить контракт/кейс
- Первым делом починить авторизацию: обновить фикстуру токена и креды для POST /auth/login, затем перезапустить прогон — это, вероятно, снимет часть каскадных 401/403.
- Для DELETE /users/{id} выдать тесту админский токен (отдельная роль), а не пользовательский; проверить, что RBAC-кейс вообще предусматривает роль.
- По GET /users поднять серверные логи/трейсы за время прогона и проверить зависимости (БД, пул соединений) — искать стектрейс 500.
- По GET /products уточнить у бэкенда актуальное имя поля (price vs cost/amount) и синхронизировать схему ответа в тесте; зафиксировать контракт.
- По POST /payments проверить логи платёжного сервиса и внешнего провайдера на зависшие вызовы; временно поднять таймаут только для диагностики и убедиться, что это не перегрузка окружения.
- По GET /orders/42 проверить наличие тестовых данных (сидинг заказа 42) и корректность baseUrl/версии API; при необходимости заменить на динамически создаваемый заказ.
- Стабилизировать тестовые данные и окружение (сидинг + фикстуры ролей), затем перезапустить полный прогон — текущий passRate 14.3% не отражает качество продукта.
