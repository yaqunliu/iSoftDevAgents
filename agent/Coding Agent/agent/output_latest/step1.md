{
  "domains": {
    "WebhookEventIngestion": {
      "description": "Handles inbound GitLab webhooks and exposes APIs for external/manual event triggering. It parses, verifies, and forwards events to the review lifecycle, enabling the system to automatically handle new code commits or merges. This module is crucial for receiving initial code changes, linking to FR-001 for automated code analysis triggers. It ensures that all inbound events are correctly registered in the system’s review pipeline.",
      "interfaces": [
        "POST /api/webhook/gitlab",
        "POST /api/event/manual-trigger"
      ]
    },
    "ReviewEventTracking": {
      "description": "Manages the review event lifecycle, state tracking, and analysis triggers. It provides query and state transition endpoints, allowing developers to select pending events and initiate specific code analysis tasks. This function correlates with the SRS use cases of selecting events and triggering code review execution, aligning with requirements to handle multiple sub-tasks. The module ensures streamlined event management across the system.",
      "interfaces": [
        "GET /api/events/pending",
        "GET /api/events/{event_id}",
        "POST /api/events/{event_id}/trigger",
        "POST /api/events/{event_id}/update-state"
      ]
    },
    "RuleManagement": {
      "description": "Provides CRUD management and validation for code review rules and prompts. It supplies active rules for usage in analysis pipelines, ensuring flexible and up-to-date checks. This module directly aligns with FR-006 for creating, modifying, and deleting custom code review rules. By capturing developer-defined logic, it helps tailor the analysis pipeline to project-specific requirements.",
      "interfaces": [
        "GET /api/rules",
        "POST /api/rules",
        "PUT /api/rules/{rule_id}",
        "DELETE /api/rules/{rule_id}"
      ]
    },
    "CodeAnalysisEngine": {
      "description": "Acts as the core entry point for automated review pipelines, orchestrating all sub-tasks and aggregating results. It coordinates triggers for security, lint, and performance checks, corresponding to SRS's automated code analysis requirements. The module ensures that each analysis job is performed efficiently, combining outcomes into a cohesive final report. It underpins FR-003 by integrating AI models for comprehensive code analysis.",
      "interfaces": [
        "run_pipeline(event_id: str, tasks: List[str]) → dict (internal)",
        "run_task(event_id: str, task: str) → dict (internal)"
      ]
    },
    "AnalyzerIntegrators": {
      "description": "Provides specialized code analysis capabilities for security, lint, and performance. Each analyzer is invoked by the CodeAnalysisEngine to deliver domain-specific checks, ensuring thorough coverage of potential code issues. This module aligns with SRS sub-task triggers for targeted analyses. By isolating specialized logic, it enhances maintainability and clarity within the overall architecture.",
      "interfaces": [
        "analyze_security(event_id, code, rule) -> Report (internal)",
        "analyze_lint(event_id, code, rule) -> Report (internal)",
        "analyze_performance(event_id, code, rule) -> Report(internal)"
      ]
    },
    "ReportingFeedback": {
      "description": "Stores and displays review outcomes, automates merge request comments, and manages developer feedback. It supports FR-004 by submitting automated comments to GitLab, ensuring the development team receives prompt code review notifications. This module also covers FR-007 by compiling comprehensive reports for developer inspection. Through feedback ingestion, it contributes to continuous improvement of the review process.",
      "interfaces": [
        "GET /api/reports/{event_id}",
        "POST /api/reports/{event_id}/gitlab-comment",
        "POST /api/reports/{event_id}/feedback"
      ]
    },
    "AnalyticsStatistics": {
      "description": "Provides aggregated analytics of review and feedback data, offering insights into quality metrics, trends, and efficiency. This module aligns with FR-008 through FR-011 by presenting acceptance rate statistics, time-series data, heatmaps, and code review duration metrics. It enables developers to access multi-dimensional analyses of system performance and code quality over time. The analytics endpoints facilitate informed decision-making and continuous optimization of the code review process.",
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