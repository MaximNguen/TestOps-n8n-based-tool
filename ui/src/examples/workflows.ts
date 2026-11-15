type WorkflowNodePayload = {
  id: string;
  type: string;
  name: string;
  position: { x: number; y: number };
  parameters: Record<string, unknown>;
  disabled?: boolean;
};

type WorkflowConnectionPayload = {
  from: string;
  to: string;
  output?: string;
};

export interface WorkflowExample {
  key: string;
  title: string;
  description: string;
  tags: string[];
  workflow: {
    name: string;
    description: string;
    active: boolean;
    nodes: WorkflowNodePayload[];
    connections: WorkflowConnectionPayload[];
  };
}

function node(
  id: string,
  type: string,
  name: string,
  x: number,
  y: number,
  parameters: Record<string, unknown> = {},
): WorkflowNodePayload {
  return { id, type, name, position: { x, y }, parameters };
}

function link(from: string, to: string, output = "main"): WorkflowConnectionPayload {
  return { from, to, output };
}

const sampleResults = {
  results: [
    {
      name: "GET /health",
      method: "GET",
      url: "https://api.demo.local/health",
      status: 200,
      passed: true,
    },
    {
      name: "GET /users",
      method: "GET",
      url: "https://api.demo.local/users",
      status: 500,
      passed: false,
      error: "Internal Server Error",
    },
    {
      name: "GET /products",
      method: "GET",
      url: "https://api.demo.local/products",
      status: 200,
      passed: false,
      error: "Schema mismatch: required field 'price' is missing",
    },
  ],
};

export const workflowExamples: WorkflowExample[] = [
  {
    key: "results-report",
    title: "Results → AI summary → report",
    description:
      "Принимает результаты тестов через webhook, строит сводку и сохраняет Markdown-отчёт.",
    tags: ["webhook", "report", "AI"],
    workflow: {
      name: "Example: results to report",
      description: "Test results webhook -> summary -> report -> file.",
      active: true,
      nodes: [
        node("trigger", "trigger.testResults", "Test results", 80, 180, {
          path: "qa/example-results",
          method: "POST",
          source: "auto",
          sample: sampleResults,
        }),
        node("summary", "ai.summarizeResults", "AI summary", 400, 180, {
          useAi: false,
          language: "ru",
          provider: "auto",
          credentialId: "",
          baseUrl: "",
          model: "",
          agent: "",
          opencodeBin: "",
        }),
        node("report", "qa.report", "Build report", 720, 180, {
          title: "QA report: example results",
        }),
        node("publish", "qa.publish", "Save report", 1040, 180, {
          channel: "file",
          path: "",
          title: "",
        }),
      ],
      connections: [
        link("trigger", "summary"),
        link("summary", "report"),
        link("report", "publish"),
      ],
    },
  },
  {
    key: "listener-pytest",
    title: "Pytest listener → report",
    description:
      "Слушает папку с отчётами pytest/Newman/JUnit и автоматически строит отчёт при новом файле.",
    tags: ["listener", "pytest", "report"],
    workflow: {
      name: "Example: pytest listener",
      description: "Watch reports folder -> summary -> report -> file.",
      active: true,
      nodes: [
        node("watch", "trigger.testResultsFile", "Watch reports folder", 80, 180, {
          directory: "C:\\path\\to\\reports",
          patterns: "results*.json,*.xml",
          source: "auto",
          intervalSeconds: 10,
        }),
        node("summary", "ai.summarizeResults", "AI summary", 400, 180, {
          useAi: false,
          language: "ru",
          provider: "auto",
          credentialId: "",
          baseUrl: "",
          model: "",
          agent: "",
          opencodeBin: "",
        }),
        node("report", "qa.report", "Build report", 720, 180, {
          title: "QA report: listener",
        }),
        node("publish", "qa.publish", "Save report", 1040, 180, {
          channel: "file",
          path: "",
          title: "",
        }),
      ],
      connections: [
        link("watch", "summary"),
        link("summary", "report"),
        link("report", "publish"),
      ],
    },
  },
  {
    key: "openapi-plan",
    title: "OpenAPI → test plan → report",
    description:
      "Генерирует тест-кейсы из OpenAPI, собирает тест-план и сохраняет отчёт.",
    tags: ["OpenAPI", "test plan", "report"],
    workflow: {
      name: "Example: OpenAPI test plan",
      description: "Manual trigger -> OpenAPI cases -> test plan -> report.",
      active: true,
      nodes: [
        node("trigger", "trigger.manual", "Manual trigger", 80, 200),
        node("openapi", "qa.openapiCases", "OpenAPI cases", 380, 200, {
          specUrl: "",
          baseUrl: "https://api.demo.local",
          include: "",
          maxCases: 20,
          includeDeprecated: false,
          spec: {
            openapi: "3.0.0",
            info: { title: "Demo API", version: "1.0.0" },
            paths: {
              "/users": {
                get: {
                  operationId: "listUsers",
                  summary: "List users",
                  responses: { "200": { description: "ok" } },
                },
              },
              "/users/{id}": {
                get: {
                  operationId: "getUser",
                  summary: "Get user",
                  parameters: [
                    {
                      name: "id",
                      in: "path",
                      required: true,
                      schema: { type: "integer", example: 42 },
                    },
                  ],
                  responses: {
                    "200": { description: "ok" },
                    "404": { description: "not found" },
                  },
                },
              },
            },
          },
        }),
        node("plan", "qa.testPlan", "Test plan", 680, 200, {
          mode: "template",
          title: "Demo API test plan",
          requirements: "Check users CRUD and error responses.",
          maxCases: 20,
          provider: "auto",
          credentialId: "",
          baseUrl: "",
          model: "",
          agent: "",
          opencodeBin: "",
          fallbackToTemplate: true,
        }),
        node("report", "qa.report", "Build report", 980, 200, {
          title: "Demo API test plan report",
        }),
        node("publish", "qa.publish", "Save report", 1280, 200, {
          channel: "file",
          path: "",
          title: "",
        }),
      ],
      connections: [
        link("trigger", "openapi"),
        link("openapi", "plan"),
        link("plan", "report"),
        link("report", "publish"),
      ],
    },
  },
  {
    key: "merge-review",
    title: "Results + code review → one report",
    description:
      "Две ветки: результаты тестов и code review. Merge собирает один общий отчёт.",
    tags: ["merge", "code review", "report"],
    workflow: {
      name: "Example: results and review merge",
      description: "Test results + code review -> one merged report.",
      active: true,
      nodes: [
        node("trigger", "trigger.testResults", "Test results", 80, 180, {
          path: "qa/example-merge",
          method: "POST",
          source: "auto",
          sample: sampleResults,
        }),
        node("summary", "ai.summarizeResults", "AI summary", 380, 100, {
          useAi: false,
          language: "ru",
          provider: "auto",
          credentialId: "",
          baseUrl: "",
          model: "",
          agent: "",
          opencodeBin: "",
        }),
        node("review", "core.code", "Autotest review", 380, 320, {
          mode: "all",
          code:
            "return [{\"title\": \"Autotest review\", \"markdown\": \"## Autotest review\\n\\n- Проверить флаки в UI-тестах.\\n- Обновить тестовые токены.\\n- Сверить схему ответа /products с OpenAPI.\"}]",
        }),
        node("merge", "core.merge", "Merge branches", 700, 200, {
          mode: "report",
        }),
        node("report", "qa.report", "Build report", 980, 200, {
          title: "Merged QA report",
        }),
        node("publish", "qa.publish", "Save report", 1260, 200, {
          channel: "file",
          path: "",
          title: "",
        }),
      ],
      connections: [
        link("trigger", "summary"),
        link("trigger", "review"),
        link("summary", "merge"),
        link("review", "merge"),
        link("merge", "report"),
        link("report", "publish"),
      ],
    },
  },
  {
    key: "postman-report",
    title: "Postman/Newman run → report",
    description:
      "Запускает Postman-коллекцию через Newman и строит отчёт по результатам.",
    tags: ["Postman", "Newman", "report"],
    workflow: {
      name: "Example: Postman run report",
      description: "Manual trigger -> Newman collection -> summary -> report.",
      active: true,
      nodes: [
        node("trigger", "trigger.manual", "Manual trigger", 80, 200),
        node("run", "qa.runCollection", "Run Postman collection", 380, 200, {
          collection: "./postman/collection.yaml",
          environment: "",
          extraArgs: "",
          timeoutSeconds: 600,
          runner: "auto",
          newmanBin: "",
          postmanBin: "",
          failOnTestFailure: false,
        }),
        node("summary", "ai.summarizeResults", "AI summary", 700, 200, {
          useAi: false,
          language: "ru",
          provider: "auto",
          credentialId: "",
          baseUrl: "",
          model: "",
          agent: "",
          opencodeBin: "",
        }),
        node("report", "qa.report", "Build report", 1020, 200, {
          title: "Postman run report",
        }),
        node("publish", "qa.publish", "Save report", 1320, 200, {
          channel: "file",
          path: "",
          title: "",
        }),
      ],
      connections: [
        link("trigger", "run"),
        link("run", "summary"),
        link("summary", "report"),
        link("report", "publish"),
      ],
    },
  },
  {
    key: "if-branches",
    title: "If branches → merge → report",
    description:
      "Делит результаты на ветки по числу падений, маркирует severity и сводит обратно в один отчёт.",
    tags: ["if", "branches", "merge"],
    workflow: {
      name: "Example: if branches",
      description: "Test results -> if -> true/false -> merge -> report.",
      active: true,
      nodes: [
        node("trigger", "trigger.testResults", "Test results", 80, 220, {
          path: "qa/example-if",
          method: "POST",
          source: "auto",
          sample: sampleResults,
        }),
        node("if", "core.if", "Has failures?", 380, 220, {
          left: "{{ $json.summary.failed }}",
          operator: "gt",
          right: 0,
          caseSensitive: false,
        }),
        node("high", "core.set", "High severity", 680, 100, {
          values: { severity: "high" },
          keepOnlySet: false,
        }),
        node("low", "core.set", "Low severity", 680, 340, {
          values: { severity: "low" },
          keepOnlySet: false,
        }),
        node("merge", "core.merge", "Merge branches", 980, 220, {
          mode: "report",
        }),
        node("report", "qa.report", "Build report", 1260, 220, {
          title: "QA report: if branches",
        }),
        node("publish", "qa.publish", "Save report", 1540, 220, {
          channel: "file",
          path: "",
          title: "",
        }),
      ],
      connections: [
        link("trigger", "if"),
        link("if", "high", "true"),
        link("if", "low", "false"),
        link("high", "merge"),
        link("low", "merge"),
        link("merge", "report"),
        link("report", "publish"),
      ],
    },
  },
  {
    key: "three-checks",
    title: "Results + review + metrics → one report",
    description:
      "Три параллельные ветки собирают сводку, code review и метрики, затем merge делает один отчёт.",
    tags: ["fan-out", "3 branches", "merge"],
    workflow: {
      name: "Example: three parallel checks",
      description:
        "Test results fan out to AI summary, code review and quality metrics, then merge.",
      active: true,
      nodes: [
        node("trigger", "trigger.testResults", "Test results", 80, 220, {
          path: "qa/example-three-checks",
          method: "POST",
          source: "auto",
          sample: sampleResults,
        }),
        node("summary", "ai.summarizeResults", "AI summary", 380, 100, {
          useAi: false,
          language: "ru",
          provider: "auto",
          credentialId: "",
          baseUrl: "",
          model: "",
          agent: "",
          opencodeBin: "",
        }),
        node("review", "core.code", "Code review", 380, 300, {
          mode: "all",
          code:
            "return [{\"title\": \"Code review\", \"markdown\": \"## Code review\\n\\n- Проверить стабильность локаторов.\\n- Добавить проверки контракта.\\n- Разделить API и UI фикстуры.\"}]",
        }),
        node("metrics", "core.set", "Quality metrics", 380, 500, {
          values: {
            title: "Quality metrics",
            markdown:
              "## Quality metrics\\n\\n- Total: {{ $json.summary.total }}\\n- Failed: {{ $json.summary.failed }}\\n- Pass rate: {{ $json.summary.passRate }}%",
          },
          keepOnlySet: true,
        }),
        node("merge", "core.merge", "Merge 3 branches", 700, 260, {
          mode: "report",
        }),
        node("report", "qa.report", "Build report", 980, 260, {
          title: "QA report: three checks",
        }),
        node("publish", "qa.publish", "Save report", 1260, 260, {
          channel: "file",
          path: "",
          title: "",
        }),
      ],
      connections: [
        link("trigger", "summary"),
        link("trigger", "review"),
        link("trigger", "metrics"),
        link("summary", "merge"),
        link("review", "merge"),
        link("metrics", "merge"),
        link("merge", "report"),
        link("report", "publish"),
      ],
    },
  },
  {
    key: "fanout-publishers",
    title: "One report → file + Slack + Jira",
    description:
      "Одна ветка строит отчёт, затем он расходится на три независимых канала публикации.",
    tags: ["fan-out", "publish", "3 branches"],
    workflow: {
      name: "Example: fan-out publishers",
      description:
        "Test results -> report -> file, Slack and Jira branches. Slack/Jira disabled until credentials are set.",
      active: true,
      nodes: [
        node("trigger", "trigger.testResults", "Test results", 80, 220, {
          path: "qa/example-publishers",
          method: "POST",
          source: "auto",
          sample: sampleResults,
        }),
        node("summary", "ai.summarizeResults", "AI summary", 380, 220, {
          useAi: false,
          language: "ru",
          provider: "auto",
          credentialId: "",
          baseUrl: "",
          model: "",
          agent: "",
          opencodeBin: "",
        }),
        node("report", "qa.report", "Build report", 700, 220, {
          title: "QA report: fan-out",
        }),
        node("file", "qa.publish", "Save to file", 1020, 100, {
          channel: "file",
          path: "",
          title: "",
        }),
        {
          ...node("slack", "qa.publish", "Publish to Slack", 1020, 260, {
            channel: "slack",
            credentialId: "",
            slackChannel: "",
            title: "",
          }),
          disabled: true,
        },
        {
          ...node("jira", "qa.publish", "Create Jira issue", 1020, 420, {
            channel: "jira",
            credentialId: "",
            projectKey: "",
            issueType: "Bug",
            title: "",
          }),
          disabled: true,
        },
      ],
      connections: [
        link("trigger", "summary"),
        link("summary", "report"),
        link("report", "file"),
        link("report", "slack"),
        link("report", "jira"),
      ],
    },
  },
  {
    key: "nested-if",
    title: "Nested If → 3 severity branches → report",
    description:
      "Два if подряд создают три ветки severity: high, medium и low. Затем все сводятся в один отчёт.",
    tags: ["if", "3 branches", "merge"],
    workflow: {
      name: "Example: nested if severity",
      description: "Nested ifs split into high/medium/low branches and merge into one report.",
      active: true,
      nodes: [
        node("trigger", "trigger.testResults", "Test results", 80, 300, {
          path: "qa/example-nested-if",
          method: "POST",
          source: "auto",
          sample: sampleResults,
        }),
        node("if-failed", "core.if", "Failures > 0?", 360, 300, {
          left: "{{ $json.summary.failed }}",
          operator: "gt",
          right: 0,
          caseSensitive: false,
        }),
        node("high", "core.set", "Severity high", 660, 140, {
          values: { severity: "high" },
          keepOnlySet: false,
        }),
        node("if-total", "core.if", "Tests exist?", 660, 380, {
          left: "{{ $json.summary.total }}",
          operator: "gt",
          right: 0,
          caseSensitive: false,
        }),
        node("medium", "core.set", "Severity medium", 960, 280, {
          values: { severity: "medium" },
          keepOnlySet: false,
        }),
        node("low", "core.set", "Severity low", 960, 480, {
          values: { severity: "low" },
          keepOnlySet: false,
        }),
        node("merge", "core.merge", "Merge severity branches", 1240, 340, {
          mode: "report",
        }),
        node("report", "qa.report", "Build report", 1520, 340, {
          title: "QA report: severity branches",
        }),
        node("publish", "qa.publish", "Save report", 1800, 340, {
          channel: "file",
          path: "",
          title: "",
        }),
      ],
      connections: [
        link("trigger", "if-failed"),
        link("if-failed", "high", "true"),
        link("if-failed", "if-total", "false"),
        link("if-total", "medium", "true"),
        link("if-total", "low", "false"),
        link("high", "merge"),
        link("medium", "merge"),
        link("low", "merge"),
        link("merge", "report"),
        link("report", "publish"),
      ],
    },
  },
];
