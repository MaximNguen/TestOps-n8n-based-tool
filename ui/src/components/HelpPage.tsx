import { useState } from "react";
import { HelpExamplesPage } from "./HelpExamplesPage";

interface HelpPageProps {
  onClose: () => void;
  onImportWorkflow: (workflow: unknown) => Promise<void>;
}

export function HelpPage({ onClose, onImportWorkflow }: HelpPageProps) {
  const [tab, setTab] = useState<"basics" | "examples">("basics");

  return (
    <div className="help-page">
      <header className="help-header">
        <div>
          <h1>TestOps n8n: справочник</h1>
          <p>
            Практическое руководство по workflow, триггерам, нодам, ветвям и
            AI-анализу.
          </p>
        </div>
        <button className="primary" onClick={onClose}>
          Back to workflows
        </button>
      </header>

      <div className="help-tabs">
        <button
          className={tab === "basics" ? "is-active" : ""}
          onClick={() => setTab("basics")}
        >
          Основы
        </button>
        <button
          className={tab === "examples" ? "is-active" : ""}
          onClick={() => setTab("examples")}
        >
          Примеры нод
        </button>
      </div>

      {tab === "basics" ? (
        <>
      <section>
        <h2>Быстрый старт</h2>
        <ol>
          <li>Выберите workflow слева или создайте новый.</li>
          <li>Добавьте ноды из палитры и соедините их мышью.</li>
          <li>Настройте параметры в инспекторе справа.</li>
          <li>Нажмите Save, чтобы применить изменения.</li>
          <li>Нажмите Run workflow.</li>
          <li>Результаты и логи смотрите в нижней панели.</li>
        </ol>
      </section>

      <section>
        <h2>Базовые действия в UI</h2>
        <ul>
          <li>
            <strong>Удалить ноду:</strong> выбрать и нажать Delete.
          </li>
          <li>
            <strong>Удалить связь:</strong> клик по линии + Delete или двойной
            клик по линии.
          </li>
          <li>
            <strong>Сохранить:</strong> Save применяет изменения к текущему
            workflow. Save workflow сохраняет копию со всеми настройками в My
            workflows.
          </li>
          <li>
            <strong>Остановить:</strong> Cancel. Для listener-режима также можно
            выключить active и Save.
          </li>
          <li>
            <strong>Retry:</strong> после ошибки над нодой появляется кнопка
            Retry. Повторяется только эта нода.
          </li>
          <li>
            <strong>Панель результатов:</strong> тянется за полосу сверху,
            двойной клик сворачивает.
          </li>
        </ul>
      </section>

      <section>
        <h2>Триггеры</h2>

        <h3>Manual trigger</h3>
        <p>
          Запуск кнопкой Run. Можно указать sample payload для ручной проверки.
        </p>
        <pre>{`{
  "type": "trigger.manual",
  "parameters": {
    "sample": { "name": "demo" }
  }
}`}</pre>

        <h3>Webhook trigger</h3>
        <p>
          Запуск по HTTP. Настройте path и method. URL:
          <code> POST /webhook/&lt;path&gt;</code>.
        </p>
        <pre>{`curl.exe -X POST "http://127.0.0.1:5678/webhook/qa/hook" \\
  -H "Content-Type: application/json" \\
  -d "{\\"ok\\": true}"`}</pre>

        <h3>Schedule trigger</h3>
        <p>Запуск по cron. Пример: каждый будний день в 09:00.</p>
        <pre>{`cron: 0 9 * * 1-5`}</pre>

        <h3>Test results trigger</h3>
        <p>
          Принимает результаты pytest/Newman/JUnit/generic JSON и сразу строит
          сводку. URL: <code>POST /webhook/qa/test-results</code>.
        </p>
        <pre>{`{
  "results": [
    {
      "name": "GET /users",
      "method": "GET",
      "url": "https://api.example.com/users",
      "status": 500,
      "passed": false,
      "error": "Internal Server Error"
    }
  ]
}`}</pre>

        <h3>Test results file trigger</h3>
        <p>
          Listener-режим: запустите workflow один раз, и он будет проверять
          папку каждые N секунд. Старые файлы игнорируются.
        </p>
        <pre>{`directory: C:\\path\\to\\reports
patterns: results*.json,*.xml
intervalSeconds: 10

pytest --json-report --json-report-file=reports/results.json`}</pre>
      </section>

      <section>
        <h2>Основные ноды</h2>

        <h3>core.set</h3>
        <p>Добавляет или перезаписывает поля в каждом item.</p>
        <pre>{`values: { "env": "stage", "tag": "{{ $json.id }}" }`}</pre>

        <h3>core.if</h3>
        <p>Делит items на ветки true и false.</p>
        <pre>{`left: {{ $json.status }}
operator: equals
right: 500`}</pre>

        <h3>core.code</h3>
        <p>
          Python-код. В режиме all доступны input_items, items, json, params,
          log. Нужно вернуть список объектов.
        </p>
        <pre>{`return [
  {"name": "custom", "payload": json}
]`}</pre>

        <h3>core.http</h3>
        <p>HTTP-запрос к внешнему API. Можно использовать credential с baseUrl.</p>

        <h3>core.merge</h3>
        <p>Объединяет несколько веток в один item.</p>
        <ul>
          <li>
            <strong>Report</strong> — главный отчёт остаётся основным, остальные
            ветки становятся секциями.
          </li>
          <li>
            <strong>Merge objects</strong> — JSON-объекты сливаются.
          </li>
          <li>
            <strong>Append</strong> — всё складывается в массив items.
          </li>
        </ul>

        <h3>QA-ноды</h3>
        <ul>
          <li>
            <code>qa.openapiCases</code> — кейсы из OpenAPI.
          </li>
          <li>
            <code>qa.testPlan</code> — тест-план (template или LLM).
          </li>
          <li>
            <code>qa.runCollection</code> — прогон Postman-коллекции через Newman
            или Postman CLI.
          </li>
          <li>
            <code>qa.report</code> — Markdown/HTML-отчёт по коду, а не AI.
          </li>
          <li>
            <code>qa.publish</code> — файл, Slack, Telegram, Confluence, Jira.
          </li>
        </ul>

        <h3>AI-ноды</h3>
        <ul>
          <li>
            <code>ai.summarizeResults</code> — короткое резюме и гипотезы о
            причинах падений.
          </li>
          <li>
            <code>ai.agent</code> — произвольный запрос к модели. Может читать
            проект через opencode, если включён Allow tools.
          </li>
        </ul>
      </section>

      <section>
        <h2>Ветвление и merge</h2>
        <p>Две ветки могут сходиться в одну ноду. Executor ждёт обе ветки.</p>
        <pre>{`testResults -> AI summary ─────┐
                               ├-> Merge branches -> Build report -> Save report
testResults -> Autotest review ┘`}</pre>
        <p>
          Вариант 1: поставить <code>core.merge</code> в режиме Report перед
          <code>qa.report</code>.
        </p>
        <p>
          Вариант 2: соединить обе ветки прямо в <code>qa.report</code>. Он сам
          выберет основной отчёт, а остальные inputs добавит секциями.
        </p>
        <pre>{`// Ветка review: сформировать Markdown
{
  "title": "Code review",
  "markdown": "{{ $json.text }}"
}`}</pre>
      </section>

      <section>
        <h2>AI Agent для code review</h2>
        <p>Чтобы модель реально читала проект:</p>
        <pre>{`Provider: opencode
Model: opencode-go/deepseek-v4.1-flash
Agent: plan
Working directory: C:\\Users\\fodit\\Desktop\\QA Projects\\VolgaIT_QA_SemiFinal_2026
Allow tools: true
Timeout (sec): 600
Retry: 1 attempt`}</pre>
        <p>
          <code>Allow tools</code> даёт доступ к чтению файлов и включает
          <code>--auto</code>. Используйте read-only агент <code>plan</code>,
          чтобы модель не меняла файлы.
        </p>
      </section>

      <section>
        <h2>Выражения</h2>
        <pre>{`{{ $json.status }}
{{ $json.user.name }}
{{ $node("OpenAPI cases").json.caseId }}
{{ len($items) }}
{{ $env.MY_VAR }}`}</pre>
      </section>

      <section>
        <h2>Retry, Cancel и параллельность</h2>
        <ul>
          <li>
            AI-ноды по умолчанию: 5 попыток с паузой 10 секунд.
          </li>
          <li>
            Остальные ноды: 1 попытка, если не указать иное в инспекторе.
          </li>
          <li>
            Retry запускает только упавшую ноду и использует сохранённый вход.
          </li>
          <li>
            Cancel прерывает текущие ноды. Долгие AI-вызовы завершаются
            принудительно.
          </li>
          <li>
            Независимые ветки выполняются параллельно. Лимит задаётся
            <code>MAX_PARALLEL_NODES</code>, по умолчанию 2-4 в зависимости от
            CPU.
          </li>
        </ul>
      </section>

      <section>
        <h2>Полезные команды</h2>
        <pre>{`# запуск движка
.\\.venv\\Scripts\\python.exe -m uvicorn app:app --app-dir backend --host 127.0.0.1 --port 5678

# pytest с JSON
pytest --json-report --json-report-file=reports/results.json

# новый прогон коллекции
newman run collection.json --reporters json --reporter-json-export newman.json

# API
POST /api/workflows/{id}/run
GET  /api/runs/{id}
POST /api/runs/{id}/cancel
POST /api/runs/{id}/retry/{nodeId}`}</pre>
      </section>

      <section>
        <h2>Docker и n8n</h2>
        <p>
          Docker Compose поднимает движок на 5678 и n8n на 5679. Из n8n в движок
          используйте <code>http://host.docker.internal:5678</code> или
          <code>http://engine:5678</code> в compose.
        </p>
      </section>
        </>
      ) : (
        <HelpExamplesPage onImportWorkflow={onImportWorkflow} />
      )}
    </div>
  );
}
