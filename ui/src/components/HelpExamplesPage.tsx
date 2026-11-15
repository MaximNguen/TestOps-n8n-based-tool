import { useState } from "react";
import { workflowExamples } from "../examples/workflows";

const EXAMPLE_PURPOSE: Record<string, string> = {
  "results-report":
    "Быстро получить понятный отчёт по результатам тестов без ручного копирования.",
  "listener-pytest":
    "Автоматически подхватывать новые pytest/Newman/JUnit отчёты из папки.",
  "openapi-plan":
    "Сгенерировать тест-кейсы и тест-план из OpenAPI и сохранить его документом.",
  "merge-review":
    "Собрать результаты тестов и code review в один общий отчёт.",
  "postman-report":
    "Прогнать Postman-коллекцию через Newman и получить разбор падений.",
  "if-branches":
    "Разделить обработку по условию и свести ветки обратно в один отчёт.",
  "three-checks":
    "Запустить три независимые проверки параллельно и собрать один отчёт.",
  "fanout-publishers":
    "Разослать один отчёт в несколько каналов параллельно.",
  "nested-if":
    "Разложить результаты на три уровня severity и свести в один отчёт.",
};

interface ExampleCardProps {
  title: string;
  type: string;
  summary: string;
  connections: string;
  params: string;
  notes?: string[];
}

function ExampleCard({
  title,
  type,
  summary,
  connections,
  params,
  notes,
}: ExampleCardProps) {
  return (
    <article className="help-example">
      <header className="help-example-head">
        <h3>{title}</h3>
        <code>{type}</code>
      </header>
      <p className="help-example-purpose">
        <strong>Для чего:</strong> {summary}
      </p>
      <div className="help-example-body">
        <div>
          <span className="help-example-label">Как соединить</span>
          <pre>{connections}</pre>
        </div>
        <div>
          <span className="help-example-label">Параметры</span>
          <pre>{params}</pre>
        </div>
      </div>
      {notes && notes.length > 0 && (
        <ul className="help-example-notes">
          {notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </article>
  );
}

interface HelpExamplesPageProps {
  onImportWorkflow: (workflow: unknown) => Promise<void>;
}

export function HelpExamplesPage({ onImportWorkflow }: HelpExamplesPageProps) {
  const [importingKey, setImportingKey] = useState<string | null>(null);

  const importExample = async (key: string, workflow: unknown) => {
    setImportingKey(key);
    try {
      await onImportWorkflow(workflow);
    } finally {
      setImportingKey(null);
    }
  };

  return (
    <div className="help-examples">
      <p className="help-lead">
        Примеры для каждой ноды: входы, выходы, параметры и корректные связи.
        Начинайте с триггера, заканчивайте publish или отчётом.
      </p>

      <section>
        <h2>Готовые workflow</h2>
        <p>
          Импортируйте шаблон в один клик. После импорта откройте его, проверьте
          пути и нажмите Run.
        </p>
        <div className="ready-workflows-grid">
          {workflowExamples.map((example) => (
            <article className="ready-workflow-card" key={example.key}>
              <h3 className="ready-workflow-purpose">
                {EXAMPLE_PURPOSE[example.key] ?? example.description}
              </h3>
              <p className="ready-workflow-pattern">{example.title}</p>
              <h4>Что делает</h4>
              <p className="ready-workflow-description">{example.description}</p>
              <div className="ready-workflow-tags">
                {example.tags.map((tag) => (
                  <span className="ready-workflow-tag" key={tag}>
                    {tag}
                  </span>
                ))}
              </div>
              <button
                className="primary"
                disabled={importingKey === example.key}
                onClick={() => void importExample(example.key, example.workflow)}
              >
                {importingKey === example.key ? "Importing…" : "Import workflow"}
              </button>
            </article>
          ))}
        </div>
      </section>

      <section>
        <h2>Правила соединения</h2>
        <ul>
          <li>Триггер всегда первый: у него нет входящих связей.</li>
          <li>
            Обычная нода имеет один вход <code>main</code> и один выход
            <code>main</code>.
          </li>
          <li>
            У <code>core.if</code> два выхода: <code>true</code> и
            <code>false</code>. Соединяйте их с разными ветками.
          </li>
          <li>
            <code>core.merge</code> и <code>qa.report</code> могут принимать
            несколько входов. Они запускаются, когда готовы все входящие ветки.
          </li>
          <li>
            Если ветка не нужна, отключите ноду через Disabled, а не оставляйте
            висящую связь.
          </li>
          <li>Для AI-нод задайте provider и model, иначе будет ошибка.</li>
        </ul>
      </section>

      <section>
        <h2>Триггеры</h2>

        <ExampleCard
          title="Manual trigger"
          type="trigger.manual"
          summary="Ручной запуск из UI или API. Подходит для отладки и запуска по кнопке."
          connections={`Manual trigger -> любая нода`}
          params={`{
  "sample": {
    "env": "stage",
    "name": "demo"
  }
}`}
          notes={[
            "Если sample пустой, на выходе будет один пустой item.",
            "Run workflow запускает весь workflow с этого триггера.",
          ]}
        />

        <ExampleCard
          title="Webhook trigger"
          type="trigger.webhook"
          summary="Запуск по HTTP. Активность workflow обязательна."
          connections={`Webhook -> Set fields -> Build report -> Save report`}
          params={`{
  "path": "qa/webhook",
  "method": "POST",
  "sample": {}
}`}
          notes={[
            "URL: POST http://127.0.0.1:5678/webhook/qa/webhook",
            "Body доступен как {{ $json.body }}.",
            "Если webhook возвращает 404, проверьте active и path.",
          ]}
        />

        <ExampleCard
          title="Schedule trigger"
          type="trigger.schedule"
          summary="Запуск по cron. Независимая ветка стартует по расписанию."
          connections={`Schedule -> OpenAPI cases -> Test plan -> Build report`}
          params={`{
  "cron": "0 9 * * 1-5"
}`}
          notes={[
            "Формат cron: минута час день месяц день_недели.",
            "Пример: каждый будний день в 09:00.",
          ]}
        />

        <ExampleCard
          title="Test results trigger"
          type="trigger.testResults"
          summary="Приём результатов тестов и мгновенный эвристический разбор."
          connections={`Test results -> AI summary -> Build report -> Save report`}
          params={`{
  "path": "qa/test-results",
  "method": "POST",
  "source": "auto",
  "sample": {
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
  }
}`}
          notes={[
            "URL: POST /webhook/qa/test-results",
            "Понимает Newman/Postman JSON, pytest-json-report, JUnit XML, generic JSON.",
            "Поле source можно оставить auto.",
          ]}
        />

        <ExampleCard
          title="Test results file trigger"
          type="trigger.testResultsFile"
          summary="Listener: workflow запускается один раз и ждёт новые файлы в папке."
          connections={`Watch reports folder -> AI summary -> Build report -> Save report`}
          params={`{
  "directory": "C:\\\\path\\\\to\\\\reports",
  "patterns": "results*.json,*.xml",
  "source": "auto",
  "intervalSeconds": 10
}`}
          notes={[
            "Старые файлы при старте игнорируются.",
            "Таймаута нет: остановить можно Cancel или active=false.",
            "pytest: pytest --json-report --json-report-file=reports/results.json",
          ]}
        />
      </section>

      <section>
        <h2>Transform и действия</h2>

        <ExampleCard
          title="Set fields"
          type="core.set"
          summary="Добавляет поля в каждый item. Работает с выражениями."
          connections={`любая нода -> Set fields -> следующая нода`}
          params={`{
  "values": {
    "environment": "stage",
    "source": "{{ $json.name }}",
    "ok": true
  },
  "keepOnlySet": false
}`}
          notes={[
            "keepOnlySet=true оставит только новые поля.",
            "Если нужен один общий объект после веток, используйте core.merge.",
          ]}
        />

        <ExampleCard
          title="If"
          type="core.if"
          summary="Делит items на два выхода: true и false."
          connections={`Manual -> If
If [true]  -> Set fields (OK)
If [false] -> Set fields (Problem)
Обе ветки можно свести в Merge branches`}
          params={`{
  "left": "{{ $json.status }}",
  "operator": "equals",
  "right": 500,
  "caseSensitive": false
}`}
          notes={[
            "Выход true: условие выполнено.",
            "Выход false: условие не выполнено.",
            "Не соединяйте оба выхода с одной нодой без merge, если нужна логика объединения.",
          ]}
        />

        <ExampleCard
          title="Code"
          type="core.code"
          summary="Python-код для нестандартной логики."
          connections={`Test results -> Code -> Build report`}
          params={`{
  "mode": "all",
  "code": "items = [item for item in input_items if item.get('tests')]\\nreturn items"
}`}
          notes={[
            "Для all доступны input_items, items, json, params, log.",
            "Верните список объектов, а не строку.",
            "Для каждого item используйте mode=each.",
          ]}
        />

        <ExampleCard
          title="HTTP request"
          type="core.http"
          summary="Вызов внешнего API. Может использовать credential с baseUrl и токеном."
          connections={`Manual -> HTTP request -> Set fields -> Build report`}
          params={`{
  "method": "GET",
  "url": "/health",
  "headers": {},
  "query": {},
  "bodyType": "json",
  "credentialId": "",
  "timeout": 30,
  "failOnError": true
}`}
          notes={[
            "Если credential содержит baseUrl, можно указать относительный url.",
            "Результат: status, headers, body, url.",
          ]}
        />

        <ExampleCard
          title="Merge branches"
          type="core.merge"
          summary="Объединяет items из нескольких веток в один."
          connections={`Test results -> AI summary -----> Merge
Test results -> Autotest review -> Merge
Merge -> Build report -> Save report`}
          params={`{
  "mode": "report"
}`}
          notes={[
            "Report: главный отчёт + дополнительные секции.",
            "Merge objects: слить JSON, последний перекрывает ключи.",
            "Append: сложить всё в items.",
          ]}
        />
      </section>

      <section>
        <h2>QA-ноды</h2>

        <ExampleCard
          title="OpenAPI cases"
          type="qa.openapiCases"
          summary="Строит тест-кейсы из OpenAPI/Swagger."
          connections={`Manual -> OpenAPI cases -> Generate test plan -> Build report`}
          params={`{
  "specUrl": "https://api.example.com/openapi.json",
  "spec": "",
  "baseUrl": "https://api.example.com",
  "include": "/users",
  "maxCases": 30,
  "includeDeprecated": false
}`}
          notes={[
            "Можно передать specUrl или вставить JSON/YAML в spec.",
            "Один item = один тест-кейс.",
          ]}
        />

        <ExampleCard
          title="Generate test plan"
          type="qa.testPlan"
          summary="Формирует тест-план из кейсов OpenAPI или текста требований."
          connections={`OpenAPI cases -> Generate test plan -> Build report`}
          params={`{
  "mode": "template",
  "title": "API test plan",
  "requirements": "Проверить CRUD пользователей и ошибки валидации.",
  "maxCases": 40,
  "provider": "auto",
  "credentialId": "",
  "model": "",
  "agent": "",
  "opencodeBin": "",
  "fallbackToTemplate": true
}`}
          notes={[
            "template работает без AI.",
            "llm использует выбранного провайдера.",
            "При ошибке LLM можно вернуться к template.",
          ]}
        />

        <ExampleCard
          title="Run Postman collection"
          type="qa.runCollection"
          summary="Запускает Newman или Postman CLI и парсит результаты."
          connections={`Generate test plan -> Run Postman collection -> AI summary -> Build report`}
          params={`{
  "collection": "./postman/collection.yaml",
  "environment": "",
  "extraArgs": "",
  "timeoutSeconds": 600,
  "runner": "auto",
  "newmanBin": "",
  "postmanBin": "",
  "failOnTestFailure": false
}`}
          notes={[
            "Для Newman нужен npm i -g newman.",
            "Postman CLI требует login для --output.",
            "Выход содержит tests, summary и analysis.",
          ]}
        />

        <ExampleCard
          title="Build report"
          type="qa.report"
          summary="Собирает Markdown/HTML-отчёт кодом, без AI."
          connections={`AI summary -> Build report -> Save report
или
Branch 1 -> Build report
Branch 2 -> Build report`}
          params={`{
  "title": "QA report"
}`}
          notes={[
            "Принимает несколько входов: основной отчёт + дополнительные секции.",
            "Обычно идёт после AI summary или core.merge.",
            "AI пишет только текстовые блоки, структуру делает код.",
          ]}
        />

        <ExampleCard
          title="Publish report"
          type="qa.publish"
          summary="Сохраняет отчёт в файл или отправляет в Slack/Telegram/Confluence/Jira."
          connections={`Build report -> Save report`}
          params={`{
  "channel": "file",
  "credentialId": "",
  "title": "",
  "path": ""
}`}
          notes={[
            "Пустой path = data/reports/<timestamp>-report.md.",
            "Для Slack/Telegram/Confluence/Jira выберите credential.",
            "Публикация обычно последняя нода.",
          ]}
        />
      </section>

      <section>
        <h2>AI-ноды</h2>

        <ExampleCard
          title="AI summary"
          type="ai.summarizeResults"
          summary="Добавляет AI-резюме и гипотезы к результатам тестов."
          connections={`Test results -> AI summary -> Build report`}
          params={`{
  "useAi": true,
  "language": "ru",
  "provider": "opencode",
  "credentialId": "",
  "baseUrl": "",
  "model": "opencode-go/deepseek-v4.1-flash",
  "agent": "",
  "opencodeBin": ""
}`}
          notes={[
            "Без AI не работает? Проверьте provider/model.",
            "AI-ноды по умолчанию делают 5 попыток с паузой 10 секунд.",
            "Если все попытки упали, нода краснеет и появляется Retry.",
          ]}
        />

        <ExampleCard
          title="AI Agent"
          type="ai.agent"
          summary="Произвольный запрос к модели. Может читать проект через opencode."
          connections={`Watch reports folder -> AI Agent -> Set fields (Code review) -> Merge -> Build report`}
          params={`{
  "provider": "opencode",
  "credentialId": "",
  "model": "opencode-go/deepseek-v4.1-flash",
  "agent": "plan",
  "cwd": "C:\\\\Users\\\\fodit\\\\Desktop\\\\QA Projects\\\\VolgaIT_QA_SemiFinal_2026",
  "allowTools": true,
  "timeoutSeconds": 600,
  "systemPrompt": "Ты senior QA-инженер.",
  "prompt": "Проведи ревью tests/ и conftest.py. Верни 5 проблем и рекомендации.",
  "responseFormat": "text",
  "temperature": 0.2
}`}
          notes={[
            "Для review включите Allow tools и задайте Working directory.",
            "Agent=plan безопаснее: он read-only.",
            "Allow tools включает --auto; не используйте на недоверенных проектах.",
            "Ответ в text или json, отдельное поле не нужно.",
          ]}
        />
      </section>

      <section>
        <h2>Примеры ветвления</h2>

        <h3>If: две ветки и общий отчёт</h3>
        <pre>{`Test results -> If
If [true]  -> Set fields "OK"   -> Merge -> Build report -> Publish
If [false] -> Set fields "FAIL" -> Merge`}</pre>
        <p>
          Merge запустится, когда завершатся обе ветки. Если одна ветка пустая,
          отчёт всё равно соберётся по второй.
        </p>

        <h3>Отчёт + code review в одном файле</h3>
        <pre>{`Test results -> AI summary -----------> Merge -> Build report -> Save report
Test results -> AI Agent -> Set fields -> Merge`}</pre>
        <p>
          В Set fields задайте <code>title: Code review</code> и
          <code>markdown: {"{{ $json.text }}"}</code>. Merge в режиме Report
          оставит основной отчёт и добавит секцию Code review.
        </p>

        <h3>Две независимые ветки без merge</h3>
        <pre>{`Webhook -> Set fields A -> Build report A -> Publish A
Webhook -> Set fields B -> Build report B -> Publish B`}</pre>
        <p>
          Так получится два отдельных отчёта. Если нужен один файл, обе ветки
          должны сходиться в одну merge/report.
        </p>
      </section>

      <section>
        <h2>Готовые схемы</h2>

        <h3>1. Результаты тестов в файл</h3>
        <pre>{`Manual/Webhook -> Test results -> AI summary -> Build report -> Save report`}</pre>

        <h3>2. Listener для pytest</h3>
        <pre>{`Watch reports folder -> Test results file -> AI summary -> Build report -> Save report`}</pre>

        <h3>{"3. OpenAPI -> тест-план"}</h3>
        <pre>{`Manual -> OpenAPI cases -> Generate test plan -> Build report -> Save report`}</pre>

        <h3>{"4. OpenAPI -> Newman -> отчёт"}</h3>
        <pre>{`Manual -> OpenAPI cases -> Test plan -> Run Postman collection -> AI summary -> Build report`}</pre>

        <h3>5. Еженедельный прогон</h3>
        <pre>{`Schedule (cron) -> Run Postman collection -> AI summary -> Build report -> Publish`}</pre>

        <h3>6. Результаты + code review</h3>
        <pre>{`Test results -> AI summary -----------------------> Merge -> Build report -> Publish
Test results -> AI Agent -> Set fields Code review -> Merge`}</pre>
      </section>

      <section>
        <h2>Частые ошибки</h2>
        <ul>
          <li>
            <strong>AI node requires a credential</strong> — provider auto, но
            нет ключа или opencode. Укажите provider=opencode или ключ.
          </li>
          <li>
            <strong>Webhook 404</strong> — workflow не active или path не совпал.
          </li>
          <li>
            <strong>Listener не подхватывает</strong> — workflow не запущен, файл
            старый или не совпал с patterns.
          </li>
          <li>
            <strong>Merge ждёт вечно</strong> — одна из входящих веток не
            connected или упала. Проверьте обе ветки.
          </li>
          <li>
            <strong>AI Agent timeout</strong> — увеличьте Timeout (sec) и
            сузьте промпт.
          </li>
          <li>
            <strong>Retry повторяет только ноду</strong> — downstream и отчёт
            не пересобираются. Для полного отчёта запустите workflow заново.
          </li>
        </ul>
      </section>
    </div>
  );
}
