# custom-n8n

Мини-движок автоматизации в стиле n8n для QA-процессов.

Бэкенд: Python (FastAPI). UI: TypeScript (React + React Flow).
Задача: автоматизировать цепочку "требования -> тест-план -> прогон автотестов ->
разбор проблем -> отчёт -> публикация".

Это не форк n8n и не его замена. Это компактный workflow-движок, который можно
запустить локально, расширять Python-нодами и связать с настоящим n8n по HTTP.

---

## Возможности

- Workflow как DAG: ноды, связи, ветвления, выражения.
- Триггеры: manual, webhook, cron, приём результатов автотестов, автоподхват файлов из папки.
- QA-ноды: OpenAPI -> тест-кейсы, тест-план, прогон коллекции, AI-резюме,
  Markdown/HTML-отчёт, публикация в файл, Slack, Telegram, Confluence, Jira.
- AI-провайдеры: opencode CLI, DeepSeek API, Anthropic Claude API,
  любой OpenAI-совместимый endpoint (GPT, Ollama, LM Studio, vLLM).
- Offline-эвристика: анализ результатов работает без модели.
- История запусков в SQLite, live-логи через SSE, отмена выполнения.
- Шифрование credentials (Fernet/AES), мастер-ключ в data/.master.key.
- UI в духе LeetCode: светлая тема, плоские цвета, визуальный редактор.
- Перетаскиваемая панель результатов снизу (drag, double-click, Hide/Show).
- Docker Compose с n8n рядом.
- Интеграция с n8n в обе стороны.

---

## Архитектура

```
+----------------+        REST + SSE        +-----------------------------+
| React Flow UI  | -----------------------> | FastAPI                     |
| TypeScript     | <----------------------- |  - Executor (DAG)           |
+----------------+                          |  - Node registry            |
                                            |  - Scheduler (cron)         |
+----------------+        webhook           |  - SSE event bus            |
| n8n / CI /     | -----------------------> |                             |
| Newman / curl  |                          +--------------+--------------+
+----------------+                                         |
                                             SQLite (workflows, credentials, runs)
                                             data/reports/*

                       +---------------------------------+------------------+
                       |                                 |                  |
                       v                                 v                  v
              opencode / DeepSeek /             Newman / Postman     Slack / Telegram /
              Claude / OpenAI / local           CLI                  Confluence / Jira
```

---

## Требования

- Python 3.13 или новее.
- Node.js 22 или новее (только для сборки UI).
- Опционально: Newman (`npm i -g newman`) для прогона Postman-коллекций.
- Опционально: Postman CLI (`postman`) для прогона через Postman.
- Опционально: opencode CLI, если нужен AI через opencode.
- Опционально: Docker и Docker Compose.

---

## Быстрый старт

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

cd ui
npm install
npm run build
cd ..

.\.venv\Scripts\python.exe -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 5678
```

Открыть http://127.0.0.1:5678.

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd ui
npm install
npm run build
cd ..

python -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 5678
```

### UI в режиме разработки

```bash
cd ui
npm run dev
```

Vite поднимет http://127.0.0.1:5173 и проксирует `/api` и `/webhook` на порт 5678.
Перед этим бэкенд должен быть запущен.

### Docker

```bash
docker compose up --build
```

- Движок: http://127.0.0.1:5678
- n8n: http://127.0.0.1:5679
- Данные движка: ./data

Если нужен Newman внутри контейнера:

```bash
INSTALL_NEWMAN=true docker compose up --build
```

В PowerShell:

```powershell
$env:INSTALL_NEWMAN="true"; docker compose up --build
```

---

## Первый запуск и демо

При первом старте создаётся SQLite-база в `data/` и демо-workflow
"QA: test results -> summary -> report -> file".

1. Откройте UI.
2. Нажмите Run workflow.
3. Нода `trigger.testResults` возьмёт sample payload из своих параметров.
4. Нода `ai.summarizeResults` построит краткое резюме.
5. Нода `qa.report` соберёт Markdown/HTML.
6. Нода `qa.publish` сохранит отчёт в `data/reports/`.

Демо использует платную модель `opencode-go/deepseek-v4.1-flash` через
авторизацию opencode. Если платить не нужно, поставьте модель
`opencode/deepseek-v4.1-flash-free`, другую модель или отключите AI
(`AI_DISABLED=1`). Без модели анализ всё равно работает на эвристике.

Демо можно запустить без UI:

```bash
curl -X POST http://127.0.0.1:5678/webhook/qa/test-results \
  -H "Content-Type: application/json" \
  -d "{\"results\":[{\"name\":\"GET /users\",\"method\":\"GET\",\"url\":\"/users\",\"status\":500,\"passed\":false,\"error\":\"Internal Server Error\"}]}"
```

Ответ: `{"runId":"...","workflowId":"..."}`.
Статус: `GET /api/runs/{runId}`.

---

## Как пользоваться

### Интерфейс

- Слева: список workflow, палитра нод, форма credentials.
- Центр: визуальный граф workflow.
- Справа: инспектор выбранной ноды.
- Снизу: результаты запуска, логи и тестовый payload.

Основные действия:

1. Выберите workflow в списке слева.
2. Нажмите Run workflow. Статус нод появится на графе.
3. Кликните по ноде, чтобы изменить параметры справа.
4. Нажмите Save, чтобы сохранить workflow.
5. Кнопка Import загружает JSON workflow из файла.
6. Панель результатов снизу можно тянуть за полосу. Двойной клик по полосе
   сворачивает или разворачивает её. Кнопка Hide/Show results делает то же самое.
   Высота панели сохраняется в браузере.
7. В Test payload можно вставить JSON, который будет передан в workflow при
   ручном запуске. Если поле пустое, используются sample-параметры триггера.

### Сценарий 1: тест-план из OpenAPI

1. Import -> `examples/openapi-pipeline.workflow.json`.
2. Откройте ноду `OpenAPI cases` и укажите `specUrl` или вставьте спецификацию
   в поле `spec`, при необходимости поменяйте `baseUrl`.
3. В ноде `Test plan` выберите режим `template` или `llm`.
4. Нажмите Run workflow.
5. Отчёт сохранится в `data/reports/`.

### Сценарий 2: результаты автотестов

1. Откройте демо-workflow.
2. В `Test results webhook` можно заменить sample payload на свой.
3. Запустите Run workflow или отправьте результаты на
   `POST /webhook/qa/test-results`.
4. Получите summary, shortSummary, likelyProblems и topFailingEndpoints.
5. Добавьте публикацию в Slack, Telegram, Confluence или Jira через `qa.publish`.

### Сценарий 3: полный пайплайн

Импортируйте `examples/full-qa-pipeline.workflow.json`:

```
OpenAPI cases -> Test plan -> Run Postman collection -> Summarize -> Report -> Publish
```

Перед запуском укажите путь к своей коллекции в ноде `Run Postman collection`.
Для Newman логин не нужен. Для Postman CLI нужен `postman login`.

### Сценарий 4: свой workflow

1. Нажмите + New.
2. Добавьте ноды из палитры.
3. Соедините выходы и входы мышью.
4. Настройте параметры в инспекторе.
5. Сохраните и запустите.

---

## Ноды

| Тип | Назначение |
| --- | --- |
| `trigger.manual` | Ручной запуск, опциональный sample payload |
| `trigger.webhook` | HTTP-триггер `POST /webhook/<path>` |
| `trigger.schedule` | Запуск по cron |
| `trigger.testResults` | Приём результатов автотестов и мгновенный разбор |
| `trigger.testResultsFile` | Автоподхват новых отчётов из папки |
| `core.set` | Добавление и перезапись полей |
| `core.if` | Ветвление по условию (true/false) |
| `core.code` | Python-код для нестандартной логики |
| `core.http` | HTTP-запрос к любому API |
| `qa.openapiCases` | Генерация кейсов из OpenAPI/Swagger |
| `qa.testPlan` | Тест-план: шаблон или LLM |
| `qa.runCollection` | Прогон коллекции через Newman или Postman CLI |
| `qa.report` | Markdown/HTML-отчёт |
| `qa.publish` | Публикация: файл, Slack, Telegram, Confluence, Jira |
| `ai.summarizeResults` | Краткое резюме результатов и вероятные причины |
| `ai.agent` | Произвольный запрос к выбранной модели |

---

## Триггер результатов автотестов

`trigger.testResults` принимает:

- Newman/Postman JSON: `{ "run": { "executions": [...] } }` или `{ "executions": [...] }`.
- Postman-подобный JSON: `{ "results": [...] }`.
- JUnit XML: `testsuite/testcase/failure`.
- Общий массив: `{ name, method, url, status, passed, error, assertions }`.
- Уже нормализованный результат: `{ "tests": [...] }`.

На выходе:

- `summary`: total, passed, failed, skipped, passRate.
- `shortSummary`: одно-два предложения о состоянии прогона.
- `likelyProblems`: зоны риска, причина, уверенность, примеры упавших тестов.
- `topFailingEndpoints`: самые проблемные endpoint'ы.
- `tests`: нормализованный список тестов.

Эвристика без AI:

| Признак | Вероятная зона |
| --- | --- |
| ECONNREFUSED, ENOTFOUND | окружение и инфраструктура |
| timeout, socket hang up | производительность или сеть |
| 5xx | бэкенд и зависимости |
| 401, 403 | авторизация и доступы |
| 404 | контракт, маршрутизация, baseUrl |
| 405, 415 | метод или Content-Type |
| 429 | лимиты и тестовые данные |
| 400, 409, 422 | валидация и данные |
| schema mismatch, assertion error | drift контракта API |
| 2xx, но ассерт упал | устаревшие ожидания теста |

`ai.summarizeResults` добавляет к этому LLM-нарратив, если провайдер настроен.
Ошибка AI не ломает workflow: остаётся эвристический отчёт.

### pytest -> JSON

Установите плагин и запустите тесты:

```powershell
.\.venv\Scripts\python.exe -m pip install pytest-json-report
.\.venv\Scripts\python.exe -m pytest --json-report --json-report-file=results.json
```

`trigger.testResults` понимает этот формат напрямую: берет `nodeid`, `outcome`,
текст assertion из `call.crash.message`, длительности фаз и строит отчёт.
Альтернатива без плагина: `pytest --junitxml=results.xml` и отправить XML.

Отправка результатов в движок:

```powershell
curl.exe -X POST "http://127.0.0.1:5678/webhook/qa/test-results" `
  -H "Content-Type: application/json" `
  --data-binary "@results.json"
```

### Передача результатов в n8n

1. В n8n создайте workflow с нодой Webhook: метод POST, путь `pytest-results`.
2. Для отладки возьмите Test URL из ноды, для постоянной работы - Production URL.
3. Отправьте JSON:

```powershell
curl.exe -X POST "http://127.0.0.1:5679/webhook-test/pytest-results" `
  -H "Content-Type: application/json" `
  --data-binary "@results.json"
```

В n8n тело запроса обычно доступно как `$json.body`. Пример Code-ноды:

```javascript
const report = $json.body ?? $json;
const tests = report.tests ?? report.results ?? [];
const failed = tests.filter((test) => {
  if (typeof test.passed === "boolean") return !test.passed;
  return test.outcome && test.outcome !== "passed";
});
return [{ json: { total: tests.length, failed: failed.length, report } }];
```

Если n8n должен вызывать движок, используйте HTTP Request на
`http://host.docker.internal:5678/webhook/qa/test-results`.

### Режим слушателя: testResultsFile

Нода `trigger.testResultsFile` работает как постоянный слушатель:

1. Вы один раз запускаете workflow кнопкой Run.
2. Запуск переходит в режим ожидания и не завершается сам.
3. Каждые 10 секунд проверяется папка с отчётами.
4. Файлы, которые уже лежали в папке на момент запуска, игнорируются.
5. Новый/изменённый файл обрабатывается: строится AI-резюме и отчёт.
6. Таймаута нет. Остановить можно кнопкой Cancel или отключением workflow
   (active=false и Save).

Параметры:

- `directory` - папка с отчётами, абсолютная или относительно корня проекта.
- `patterns` - маски через запятую, например `results*.json,*.xml,newman*.json`.
- `source` - `auto`, `pytest`, `generic`, `junit`, `newman`.
- `intervalSeconds` - период опроса, по умолчанию 10 секунд.

Пример: `examples/file-watch-pipeline.workflow.json`.

Порядок работы:

1. Импортируйте пример.
2. Нажмите Run workflow один раз. Запуск останется в статусе running.
3. Запустите pytest с отчётом в папку слушателя:

```powershell
pytest --json-report --json-report-file=data/inbox/results.json
```

4. Через 10-20 секунд слушатель подхватит файл, выполнит workflow и создаст отчёт.
5. Чтобы остановить, нажмите Cancel или отключите workflow.

Ограничения:

- движок должен быть запущен;
- после перезапуска движка слушатель нужно запустить снова кнопкой Run;
- старые файлы игнорируются всегда;
- в Docker папка должна быть смонтирована внутрь контейнера, а `directory`
  должен указывать на путь внутри контейнера;
- для максимальной надёжности в CI лучше отправлять отчёт webhook-ом, а не
  полагаться на файловый слушатель.

---

## Формат workflow и выражения

```json
{
  "id": "wf-1",
  "name": "QA pipeline",
  "active": true,
  "nodes": [
    {
      "id": "trigger",
      "type": "trigger.testResults",
      "name": "Results",
      "position": { "x": 80, "y": 180 },
      "parameters": { "path": "qa/test-results", "source": "auto" }
    },
    {
      "id": "summary",
      "type": "ai.summarizeResults",
      "name": "Summary",
      "position": { "x": 400, "y": 180 },
      "parameters": {
        "useAi": true,
        "language": "ru",
        "provider": "opencode",
        "model": "opencode-go/deepseek-v4.1-flash"
      }
    }
  ],
  "connections": [
    { "from": "trigger", "to": "summary", "output": "main" }
  ]
}
```

Строки с `{{ ... }}` вычисляются на Python:

- `$json` - JSON первого входного item, работает `$json.user.name`.
- `$items` - все входные items.
- `$item(0)` - JSON item по индексу.
- `$node("Name")` - результат другой ноды, доступны `.json` и `.items`.
- `$env` - переменные окружения.
- `$now`, `$run`, `$workflow`.
- Безопасный набор builtins, модули `json`, `re`, `math`, `datetime`.

Примеры:

```text
{{ $json.status }}
{{ $json.user.name }}
{{ $node("OpenAPI cases").json.caseId }}
{{ len($items) }}
```

`core.if` вычисляет left/right для каждого item, поэтому ветвление работает поштучно.

---

## AI: как поменять модель или провайдера

Поддерживаются четыре варианта:

| Provider | Что использует | Ключ |
| --- | --- | --- |
| `opencode` | локальный CLI `opencode run`, ваши логины и модели | не нужен |
| `deepseek` | официальный https://api.deepseek.com | DEEPSEEK_API_KEY |
| `anthropic` | официальный https://api.anthropic.com/v1/messages | ANTHROPIC_API_KEY |
| `openai` | GPT и любой OpenAI-совместимый endpoint | OPENAI_API_KEY |
| `auto` | opencode -> deepseek -> anthropic -> openai | по обстоятельствам |

### Способ 1: поменять в UI (самый быстрый)

1. Выберите ноду `ai.summarizeResults`, `ai.agent` или `qa.testPlan`.
2. В инспекторе откройте Provider.
3. Выберите провайдера.
4. Укажите Model. Для opencode формат `provider/model`.
5. Если нужен ключ, создайте credential слева и выберите его в поле AI credential.
6. Сохраните workflow.

Примеры значений:

```text
Provider: opencode
Model: opencode-go/deepseek-v4.1-flash

Provider: opencode
Model: opencode/deepseek-v4.1-flash-free

Provider: opencode
Model: opencode-go/claude-haiku-5-5

Provider: opencode
Model: openai/gpt-5-mini

Provider: deepseek
Model: deepseek-flash

Provider: deepseek
Model: deepseek-v4-pro

Provider: anthropic
Model: claude-sonnet-4-5

Provider: openai
Model: gpt-4o-mini
```

Список моделей opencode:

```bash
opencode models
```

Список моделей нужного провайдера:

```bash
opencode models openai
opencode models opencode-go
```

### AI Agent для code review

По умолчанию `ai.agent` не даёт модели доступ к файлам. Для ревью проекта:

1. В ноде `ai.agent` выберите `Provider = opencode`.
2. Укажите `Model`.
3. Заполните `Working directory` — путь к проекту, например
   `C:\Users\fodit\Desktop\QA Projects\VolgaIT_QA_SemiFinal_2026`.
4. Включите `Allow tools`.
5. Рекомендуется указать `opencode agent = plan` — это read-only режим.
6. В `Prompt` напишите задачу, например:
   `Analyze the codebase and autotests. Return strengths, risks and recommendations.`

При `Allow tools` движок запускает opencode с `--auto`, чтобы инструменты
работали без интерактивных подтверждений. Модель может читать файлы проекта.
Используйте `agent = plan`, если не хотите, чтобы она могла менять файлы.

Ответ ноды:

- `text` — обычный текст ревью;
- `json` — если выбран `Response format = JSON`.

Отдельное поле для ответа не нужно. Для отчёта можно преобразовать:

```json
{
  "title": "Code review",
  "markdown": "{{ $json.text }}"
}
```

и передать в `core.merge` вместе с результатами тестов, а затем в `qa.report`.

### Способ 2: через .env

Скопируйте `.env.example` в `.env` и задайте значения. После изменения
перезапустите бэкенд.

```dotenv
# opencode CLI
OPENCODE_BIN=opencode
OPENCODE_MODEL=opencode-go/deepseek-v4.1-flash
OPENCODE_AGENT=
OPENCODE_CWD=

# DeepSeek
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-flash

# Anthropic Claude
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_MODEL=claude-sonnet-4-5

# OpenAI / GPT
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4o-mini
```

Эти значения используются как значения по умолчанию, если в ноде поле пустое.

### Способ 3: через credential

Слева в Credentials создайте credential:

- type `opencode`:

```json
{
  "bin": "opencode",
  "model": "opencode-go/deepseek-v4.1-flash",
  "agent": "",
  "cwd": ""
}
```

- type `deepseek`:

```json
{
  "apiKey": "sk-...",
  "baseUrl": "https://api.deepseek.com",
  "model": "deepseek-flash"
}
```

- type `anthropic`:

```json
{
  "apiKey": "sk-ant-...",
  "baseUrl": "https://api.anthropic.com",
  "model": "claude-sonnet-4-5"
}
```

- type `ai` или `openai`:

```json
{
  "baseUrl": "https://api.openai.com/v1",
  "apiKey": "sk-...",
  "model": "gpt-4o-mini"
}
```

Затем выберите этот credential в ноде. Явный тип credential имеет приоритет
над переменными окружения при `provider = auto`.

### Если у вас GPT

Вариант A: opencode.

```text
Provider: opencode
Model: openai/gpt-5-mini
```

Нужно, чтобы OpenAI был авторизован в opencode (`opencode auth list`).

Вариант B: прямой OpenAI API.

```dotenv
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini
```

или в ноде: Provider = OpenAI-compatible API, API key в credential.

### Если у вас Claude

Вариант A: opencode.

```text
Provider: opencode
Model: opencode-go/claude-haiku-5-5
```

Вариант B: прямой Anthropic API.

```dotenv
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-5
```

или credential типа `anthropic`. Используется нативный `/v1/messages`,
не OpenAI-совместимый endpoint.

### Локальная модель

Ollama:

```bash
ollama pull llama3.1
ollama serve
```

В ноде:

```text
Provider: openai
Base URL: http://localhost:11434/v1
Model: llama3.1
API key: ollama
```

LM Studio: Base URL `http://localhost:1234/v1`.
vLLM и другие OpenAI-совместимые серверы: укажите их Base URL и модель.

### Offline-режим

`AI_DISABLED=1` отключает вызовы моделей. `ai.summarizeResults` работает на
эвристике, `qa.testPlan` в режиме llm падает обратно в шаблон, `ai.agent`
возвращает понятную ошибку.

---

## Retry и повтор ноды

У каждой ноды есть настройки Retry в инспекторе:

- Max attempts - сколько раз выполнять ноду при ошибке.
- Delay (sec) - пауза между попытками.

Значения по умолчанию:

- AI-ноды: 5 попыток с паузой 10 секунд;
- остальные ноды: 1 попытка, если не указать иное.

Если AI не отвечает, нода делает 5 попыток. После последней неудачи:

- нода обводится красным;
- показывается текст ошибки;
- над нодой справа появляется кнопка Retry.

Retry повторяет только эту ноду и следующие за ней, используя сохранённый вход
неудачного запуска. Заново запускать весь workflow не нужно. Вход ноды хранится
в SQLite; если он больше 4 МБ, повтор недоступен, нужно запустить workflow заново.

Для listener-режима Retry применяется к дочернему запуску, в котором упала нода.

## Merge нескольких веток

Executor поддерживает схождение нескольких веток в одну ноду: целевая нода
запускается один раз и получает items из всех входящих веток.

Для сборки одного отчёта из нескольких веток:

1. Добавьте `core.merge` перед `qa.report`.
2. Выберите режим:
   - `Report` - основной отчёт остаётся главным, остальные ветки добавляются
     в `extraSections`;
   - `Merge objects` - JSON-объекты сливаются в один (последний перекрывает
     совпавшие ключи);
   - `Append as items array` - всё складывается в `items`.
3. Соедините выходы обеих веток со входом `core.merge`.

`qa.report` также умеет принимать несколько входов напрямую: он выбирает
основной отчёт, а остальные inputs добавляет секциями.

Пример: `examples/merge-report.workflow.json`.

```text
testResults -> AI summary ─────┐
                               ├-> Merge branches -> Build report -> Save report
testResults -> Autotest review ┘
```

Если ветка вернула `markdown`, она добавляется как готовая секция. Если вернула
`review`, `text` или произвольный JSON, он попадёт в отчёт как JSON-блок.

## Пайплайн QA

Типовой маршрут:

1. `qa.openapiCases` строит кейсы из OpenAPI/Swagger.
2. `qa.testPlan` собирает тест-план (шаблон или LLM).
3. `qa.runCollection` прогоняет Postman-коллекцию через Newman или Postman CLI.
4. `trigger.testResults` или `ai.summarizeResults` нормализует результаты.
5. `ai.summarizeResults` добавляет гипотезы о причинах.
6. `qa.report` собирает Markdown/HTML.
7. `qa.publish` отправляет отчёт в файл, Slack, Telegram, Confluence или Jira.

Готовые примеры:

- `examples/qa-pipeline.workflow.json` - результаты -> AI-резюме -> отчёт -> файл.
- `examples/openapi-pipeline.workflow.json` - OpenAPI -> тест-план -> отчёт.
- `examples/full-qa-pipeline.workflow.json` - полный пайплайн с Newman.
- `examples/postman/smoke.collection.json` - минимальная коллекция для проверки.
- `examples/n8n-import.workflow.json` - workflow для импорта в n8n.

---

## Postman и Newman

`qa.runCollection` поддерживает два раннера.

Newman, логин не нужен:

```text
newman run <collection> [-e env] [extraArgs] \
  --reporters json --reporter-json-export <tmp>/newman-report.json --suppress-exit-code
```

Postman CLI:

```text
postman collection run <collection> [-e env] [extraArgs] --output <tmp> --silent -x
```

Важно: Postman CLI требует `postman login` для `--output`. Без логина он
завершится ошибкой. Поэтому по умолчанию используется Newman.

Параметры:

- `runner = auto | newman | postman`.
- `NEWMAN_BIN` или `newmanBin`.
- `POSTMAN_BIN` или `postmanBin`.
- `failOnTestFailure = false` - workflow продолжается, отчёт строится.
- `failOnTestFailure = true` - нода падает при наличии failed-тестов.

---

## API

| Метод | Путь | Назначение |
| --- | --- | --- |
| GET | `/api/health` | Проверка состояния |
| GET | `/api/nodes` | Каталог нод |
| GET, POST | `/api/workflows` | Список и создание |
| GET, PUT, DELETE | `/api/workflows/{id}` | Чтение, обновление, удаление |
| POST | `/api/workflows/import` | Импорт JSON |
| POST | `/api/workflows/{id}/run` | Запуск: `{ data, startNodeId }` |
| GET | `/api/runs?workflowId=` | История |
| GET | `/api/runs/{id}` | Детали запуска |
| POST | `/api/runs/{id}/cancel` | Отмена |
| GET | `/api/runs/{id}/events` | SSE live-события |
| GET, POST, PUT, DELETE | `/api/credentials` | Credentials |
| ANY | `/webhook/{path}` | Webhook-триггеры |

Swagger: http://127.0.0.1:5678/docs.

---

## Интеграция с n8n

### n8n -> custom-n8n

Импортируйте `examples/n8n-import.workflow.json` в n8n.

URL движка:

| Где n8n | URL |
| --- | --- |
| n8n в Docker Compose рядом с движком | `http://engine:5678/webhook/qa/test-results` |
| n8n в Docker, движок на хосте | `http://host.docker.internal:5678/webhook/qa/test-results` |
| оба на хосте | `http://127.0.0.1:5678/webhook/qa/test-results` |

### n8n запускает workflow движка по API

```text
POST http://engine:5678/api/workflows/<workflowId>/run
Content-Type: application/json

{ "data": { "results": [ ... ] } }
```

Ответ содержит `runId`. Статус: `GET /api/runs/{runId}`.

### custom-n8n вызывает n8n

Добавьте ноду `core.http`:

```json
{
  "method": "POST",
  "url": "http://host.docker.internal:5679/webhook/<your-n8n-webhook>",
  "bodyType": "json",
  "body": { "summary": "{{ $json.shortSummary }}" }
}
```

### Нативная нода n8n

Не входит в поставку. При необходимости пишется отдельный TS-пакет
`n8n-nodes-...`, который внутри вызывает REST API этого движка.

---

## Docker

`docker-compose.yml` поднимает два сервиса:

- `engine` - этот движок на порту 5678.
- `n8n` - n8n на порту 5679.

Переменные:

- `WORKFLOW_SECRET` - мастер-ключ credentials.
- `AI_BASE_URL`, `AI_MODEL`, `OPENAI_API_KEY`.
- `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`.
- `INSTALL_NEWMAN=true` - добавить Newman в образ.

Ограничения контейнера:

- opencode в образ не входит. Для `provider = opencode` установите и
  авторизуйте opencode внутри контейнера или запускайте движок на хосте.
- для `provider = deepseek` / `anthropic` / `openai` достаточно ключей.

---

## Переменные окружения

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | Адрес сервера |
| `PORT` | `5678` | Порт |
| `DATA_DIR` | `./data` | SQLite, отчёты, мастер-ключ |
| `WORKFLOW_SECRET` | авто | Мастер-ключ credentials |
| `POSTMAN_BIN` | `postman` | Postman CLI |
| `NEWMAN_BIN` | `newman` | Newman |
| `AI_BASE_URL` | OpenAI | Base URL OpenAI-совместимого API |
| `AI_MODEL` | `gpt-4o-mini` | Модель по умолчанию |
| `OPENAI_API_KEY` | пусто | Ключ OpenAI |
| `OPENAI_BASE_URL` | OpenAI | Альтернатива AI_BASE_URL |
| `OPENAI_MODEL` | `gpt-4o-mini` | Альтернатива AI_MODEL |
| `DEEPSEEK_API_KEY` | пусто | Ключ DeepSeek |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` | Base URL DeepSeek |
| `DEEPSEEK_MODEL` | `deepseek-flash` | Модель DeepSeek |
| `ANTHROPIC_API_KEY` | пусто | Ключ Anthropic |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | Base URL Anthropic |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5` | Модель Claude |
| `OPENCODE_BIN` | пусто | Путь к opencode |
| `OPENCODE_MODEL` | пусто | Модель opencode |
| `OPENCODE_AGENT` | пусто | Агент opencode |
| `OPENCODE_CWD` | пусто | Рабочая директория opencode |
| `AI_DISABLED` | пусто | `1` отключает вызовы AI |

---

## Безопасность

- `core.code` и выражения выполняют пользовательский код на сервере.
- `opencode` запускается как агент с доступом к инструментам и файлам.
- Запускайте только доверенные workflow.
- Аутентификации в UI по умолчанию нет. Держите движок в доверенной сети
  или поставьте reverse proxy с авторизацией.
- Credentials шифруются мастер-ключом. Смена `WORKFLOW_SECRET` делает старые
  credentials нечитаемыми.
- Не храните токены в JSON workflow. Используйте credentials.
- AI-провайдеры получают текст запроса и результаты тестов. Для чувствительных
  данных используйте локальную модель.
- `opencode` использует вашу локальную авторизацию и может выполнять команды.
  Не давайте ему доступ к среде, которую нельзя менять.

---

## Тесты

```bash
python -m pytest tests -q
```

Покрыто:

- выражения и dot-access;
- шифрование credentials;
- ветвление executor;
- нормализация результатов и эвристический разбор;
- парсинг событий opencode;
- выбор AI-провайдера (opencode, deepseek, anthropic);
- API smoke: seed, запуск, webhook.

UI:

```bash
cd ui
npm run build
```

---

## Диагностика

### Порт занят

Поменяйте порт:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app:app --app-dir backend --port 5679
```

### opencode не найден

```powershell
opencode --version
```

Укажите путь:

```dotenv
OPENCODE_BIN=C:\Users\<user>\AppData\Roaming\npm\opencode.cmd
```

### opencode: Model access is disabled

Модель недоступна вашему аккаунту. Посмотрите список:

```bash
opencode models
```

Выберите другую модель или включите доступ в консоли opencode.

### DeepSeek 401 или 403

Проверьте `DEEPSEEK_API_KEY` и баланс аккаунта. Модель по умолчанию:
`deepseek-flash`.

### Anthropic 404 или model not found

Укажите актуальный model ID из консоли Anthropic в `ANTHROPIC_MODEL`
или в поле Model ноды.

### Postman CLI requires login

Для `--output` нужен `postman login`. Используйте `runner = newman`.

### Newman not found

```bash
npm install -g newman
```

### Не расшифровываются credentials

Изменился `WORKFLOW_SECRET` или удалён `data/.master.key`. Верните прежний
секрет или создайте credentials заново.

### UI не открывается

Проверьте, что собран `ui/dist`:

```bash
cd ui
npm run build
```

---

## Структура проекта

```
backend/
  app.py                 FastAPI, lifespan, seed демо-workflow
  config.py              конфигурация и .env
  scheduler.py           cron-планировщик
  api/routes.py          REST, SSE, webhook
  engine/                executor, expressions, registry, events, types
  nodes/                 ноды: triggers, core, qa, ai, publish
  store/                 SQLite и шифрование
ui/
  src/                   React + React Flow
  dist/                  собранный UI
examples/                готовые workflow и Postman-коллекция
tests/                   pytest
Dockerfile
docker-compose.yml
requirements.txt
.env.example
```

---

## Ограничения и развитие

Текущие ограничения:

- нет retry/backoff и per-node timeout;
- нет очередей и горизонтального масштабирования;
- нет версионирования workflow и RBAC;
- нет встроенной аутентификации;
- Newman/Postman CLI ставятся отдельно;
- opencode требует локальной установки и авторизации.

Возможные направления:

1. Retry, timeout и политики ошибок на уровне ноды.
2. Очередь задач и воркеры.
3. Версионирование workflow и diff.
4. Нативная community-node для n8n.
5. Шаблоны отчётов Allure/JUnit/TestRail.
6. Генерация Postman-коллекции из тест-плана.
7. RBAC и аудит действий.
