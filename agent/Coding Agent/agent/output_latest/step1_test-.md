{
  "domains": {
    "WebhookEventIngestion": {
      "description": "Handles inbound GitLab webhooks and a manual event triggering API. It parses and validates incoming payloads, then forwards them for further processing. It ensures events from external sources are accurately captured. This module initiates the review lifecycle based on external triggers. By capturing system inputs from outside, it serves as an essential entry point for all subsequent code review processes.",
      "interfaces": [
        "POST /api/webhook/gitlab",
        "POST /api/event/manual-trigger"
      ]
    },
    "ReviewEventTracking": {
      "description": "Coordinates the entire review event lifecycle, from creation to completion. It manages state transitions and triggers the analysis pipeline when events are ready. It stores pending, active, and completed events for retrieval. This module provides endpoints for listing, selecting, and updating events. By controlling the review state, it ensures that analysis tasks are initiated at the correct time.",
      "interfaces": [
        "GET /api/events/pending",
        "GET /api/events/{event_id}",
        "POST /api/events/{event_id}/trigger",
        "POST /api/events/{event_id}/update-state"
      ]
    },
    "RuleManagement": {
      "description": "Handles the creation, modification, and deletion of code review rules. It provides an interface for users to define customized rule sets that shape the analysis pipeline. This module validates user inputs and ensures the correct application of rules in code analysis. It is central to the system’s flexible policy enforcement. By maintaining rule data, it supplies active rules to the analysis engine and sub-tasks.",
      "interfaces": [
        "GET /api/rules",
        "POST /api/rules",
        "PUT /api/rules/{rule_id}",
        "DELETE /api/rules/{rule_id}"
      ]
    },
    "CodeAnalysisEngine": {
      "description": "Acts as the orchestrator for automated code analysis pipelines. It receives triggers from the event tracking module and coordinates specialized analyzers to check code for vulnerabilities, style improvements, and performance aspects. This module aggregates results and ensures each sub-task is completed systematically. Leveraging configured rules, it ensures that the correct analyzers are invoked. By centralizing analysis orchestration, it streamlines the entire review process.",
      "interfaces": [
        "run_pipeline(event_id: str, tasks: List[str]) → dict (internal)",
        "run_task(event_id: str, task: str) → dict (internal)"
      ]
    },
    "AnalyzerIntegrators": {
      "description": "Provides specialized code analysis functionalities in security, linting, and performance. Each integrator targets a distinct domain of code quality and returns consolidated reports to the engine. This module performs synchronous checks to ensure immediate feedback for each event. By applying advanced AI-based analysis, it handles the heavy-lifting of detection and classification. It strictly operates under the coordination of the code analysis engine.",
      "interfaces": [
        "analyze_security(event_id, code, rule) -> Report (internal)",
        "analyze_lint(event_id, code, rule) -> Report (internal)",
        "analyze_performance(event_id, code, rule) -> Report(internal)"
      ]
    },
    "ReportingFeedback": {
      "description": "Facilitates the persistence and retrieval of finalized review outcomes. It automates communication with GitLab by posting comments and merges relevant feedback from developers. This module allows developers to query detailed reports and submit their acceptance or rejection decisions. By capturing feedback, it drives iterative improvements to the review process. It serves as the main interface for final results distribution and developer engagement.",
      "interfaces": [
        "GET /api/reports/{event_id}",
        "POST /api/reports/{event_id}/gitlab-comment",
        "POST /api/reports/{event_id}/feedback"
      ]
    },
    "AnalyticsStatistics": {
      "description": "Aggregates performance and quality metrics across multiple reviews, such as acceptance rates and issue frequency. It stores historical data to provide trend analysis and visual heatmaps over time. This module helps quantify code review effectiveness and identifies hot-spot areas of code issues. By exposing analytics endpoints, it supports informed decision-making and improvements to development workflows. It complements the reporting module by offering deeper insights and historical comparisons.",
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