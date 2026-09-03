{
  "domains": {
    "WebhookEventIngestion": {
      "description": "Receives and processes inbound GitLab webhooks, initiating the review lifecycle as needed. The module also offers APIs for manual event triggering, ensuring external or ad-hoc events can start the code review process. In line with FR-001, it triggers the automated code review pipeline whenever new commits or merge requests occur. It carefully validates incoming data before forwarding events to the subsequent tracking module.",
      "interfaces": [
        "POST /api/webhook/gitlab",
        "POST /api/event/manual-trigger"
      ]
    },
    "ReviewEventTracking": {
      "description": "Coordinates the entire code review event lifecycle, from creation to final state. Provides endpoints for querying event status and triggering analysis, in line with SRS use cases like selecting pending events or triggering code reviews. This module orchestrates the transition of an event’s state and ensures that the appropriate tasks are triggered at the correct time. It also logs state changes for future reference.",
      "interfaces": [
        "GET /api/events/pending",
        "GET /api/events/{event_id}",
        "POST /api/events/{event_id}/trigger",
        "POST /api/events/{event_id}/update-state"
      ]
    },
    "RuleManagement": {
      "description": "Provides full CRUD capabilities for code review rules, enabling developers to define, modify, or remove custom rules. In line with the SRS, it addresses use cases like creating or adjusting rules for targeted code analysis. This module validates rules to ensure they meet the system’s format and logic requirements. It supplies the active set of rules to the analysis pipeline on demand.",
      "interfaces": [
        "GET /api/rules",
        "POST /api/rules",
        "PUT /api/rules/{rule_id}",
        "DELETE /api/rules/{rule_id}"
      ]
    },
    "CodeAnalysisEngine": {
      "description": "Acts as the core entry point for initiating automated code analysis pipelines. Coordinates sub-tasks such as security analysis, lint checks, and performance optimization, as outlined in the SRS. The engine waits for triggers from the event tracking module and retrieves the appropriate rules from the RuleManagement module. Finally, it aggregates the results of each sub-task and passes them along for reporting.",
      "interfaces": [
        "run_pipeline(event_id: str, tasks: List[str]) → dict (internal)",
        "run_task(event_id: str, task: str) → dict (internal)"
      ]
    },
    "AnalyzerIntegrators": {
      "description": "Implements the actual code analysis tasks needed for specialized domains like security, lint adherence, and performance optimization. Each integrator runs synchronously under the orchestration of the CodeAnalysisEngine, ensuring results are gathered promptly. They leverage integrated AI models for comprehensive analysis, as described in the SRS. These sub-components produce detailed findings that are fed back into the engine for further processing.",
      "interfaces": [
        "analyze_security(event_id, code, rule) -> Report (internal)",
        "analyze_lint(event_id, code, rule) -> Report (internal)",
        "analyze_performance(event_id, code, rule) -> Report(internal)"
      ]
    },
    "ReportingFeedback": {
      "description": "Collects and stores code review results, generating comprehensive reports for developer consumption. The module automates the posting of code review comments to GitLab merge requests and enables developers to provide feedback on reported issues. In line with the SRS, it supports features such as feedback submission for continuous refinement of the rules and process. This module also interacts with AnalyticsStatistics to consolidate data for trend analysis.",
      "interfaces": [
        "GET /api/reports/{event_id}",
        "POST /api/reports/{event_id}/gitlab-comment",
        "POST /api/reports/{event_id}/feedback"
      ]
    },
    "AnalyticsStatistics": {
      "description": "Aggregates historical code review and feedback data to provide insights into review efficiency, quality trends, and common issues. It offers analytics features such as acceptance rate calculations, trend visualizations, and heatmaps, as outlined in the SRS. Developers can query these metrics to identify improvement areas and monitor the impact of new rules. The module relies on the data provided by the ReportingFeedback module to build statistical representations.",
      "interfaces": [
        "GET /api/analytics/summary",
        "GET /api/analytics/heatmap",
        "GET /api/analytics/timeseries",
        "POST /api/analytics/report/{report_id}/decision"
      ]
    }
  },
  "system_dag": {
    "entry_modules": [
      "WebhookEventIngestion"
    ],
    "edges": [
      {
        "from": "WebhookEventIngestion",
        "to": "ReviewEventTracking",
        "evidence": "Webhook --> EventTracking : createEvent(), updateEvent()"
      },
      {
        "from": "ReviewEventTracking",
        "to": "CodeAnalysisEngine",
        "evidence": "EventTracking --> AnalysisEngine : run_pipeline(), run_task()"
      },
      {
        "from": "CodeAnalysisEngine",
        "to": "AnalyzerIntegrators",
        "evidence": "AnalysisEngine --> Analyzers : analyze_security(), etc."
      },
      {
        "from": "CodeAnalysisEngine",
        "to": "RuleManagement",
        "evidence": "AnalysisEngine --> RuleMgmt : get_active_rules()"
      },
      {
        "from": "CodeAnalysisEngine",
        "to": "ReportingFeedback",
        "evidence": "AnalysisEngine --> Reporting : submit_report()"
      },
      {
        "from": "ReportingFeedback",
        "to": "AnalyticsStatistics",
        "evidence": "Reporting --> Analytics : store_report(), get_trend_data()"
      }
    ]
  }
}