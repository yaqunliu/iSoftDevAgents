{
  "modules": {
    "WebhookEventIngestion": {
      "description": "Handles inbound GitLab webhooks and exposes APIs for external/manual event triggering. It parses, verifies, and forwards events to the review lifecycle, enabling the system to automatically handle new code commits or merges.",
      "entities": [
        "ReviewEvent"
      ],
      "methods": {
        "HandleGitLabWebhook": {
          "method_name": "HandleGitLabWebhook",
          "module": "WebhookEventIngestion",
          "class": "EventIngestionController",
          "description": "Receives and validates GitLab webhook events (FR-001). Creates a new ReviewEvent with parsed code and sets state to 'pending' for automated review. This enables the system to react immediately to new code submissions.",
          "type": "external_api",
          "http": {
            "verb": "POST",
            "route": "/api/webhook/gitlab"
          },
          "input": {
            "fields": {
              "payload": {
                "type": "string",
                "entity_field": null,
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": "ReviewEvent.event_id"
              },
              "state": {
                "type": "enum",
                "entity_field": "ReviewEvent.state"
              },
              "source": {
                "type": "str",
                "entity_field": "ReviewEvent.source"
              },
              "code": {
                "type": "str",
                "entity_field": "ReviewEvent.code"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "ReviewEvent",
              "operation": "create"
            }
          ]
        },
        "HandleManualTrigger": {
          "method_name": "HandleManualTrigger",
          "module": "WebhookEventIngestion",
          "class": "EventIngestionController",
          "description": "Receives manual event trigger requests and creates a new ReviewEvent with the provided code context. Sets the event state to 'pending' for subsequent analysis (aligns with domain-driven manual triggers).",
          "type": "external_api",
          "http": {
            "verb": "POST",
            "route": "/api/event/manual-trigger"
          },
          "input": {
            "fields": {
              "payload": {
                "type": "string",
                "entity_field": null,
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": "ReviewEvent.event_id"
              },
              "state": {
                "type": "enum",
                "entity_field": "ReviewEvent.state"
              },
              "source": {
                "type": "str",
                "entity_field": "ReviewEvent.source"
              },
              "code": {
                "type": "str",
                "entity_field": "ReviewEvent.code"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "ReviewEvent",
              "operation": "create"
            }
          ]
        }
      }
    },
    "ReviewEventTracking": {
      "description": "Manages the review event lifecycle, state tracking, and analysis triggers. It provides query and state transition endpoints for developers to select pending events and initiate code review tasks.",
      "entities": [
        "ReviewEvent"
      ],
      "methods": {
        "GetPendingEvents": {
          "method_name": "GetPendingEvents",
          "module": "ReviewEventTracking",
          "class": "ReviewEventTracker",
          "description": "Retrieves a list of events currently in pending state (SRS use case: 选择待审查事件). Allows developers to find review events awaiting processing.",
          "type": "external_api",
          "http": {
            "verb": "GET",
            "route": "/api/events/pending"
          },
          "input": {
            "fields": {
            }
          },
          "output": {
            "fields": {
              "events": {
                "type": "array",
                "entity_field": null
              }
            }
          },
          "entity_operations": [
            {
              "entity": "ReviewEvent",
              "operation": "read"
            }
          ]
        },
        "GetEvent": {
          "method_name": "GetEvent",
          "module": "ReviewEventTracking",
          "class": "ReviewEventTracker",
          "description": "Retrieves details of a specific review event (SRS use case: 选择待审查事件). Provides the event data needed for further analysis or manual inspection.",
          "type": "external_api",
          "http": {
            "verb": "GET",
            "route": "/api/events/{event_id}"
          },
          "input": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": "ReviewEvent.event_id",
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": "ReviewEvent.event_id"
              },
              "state": {
                "type": "enum",
                "entity_field": "ReviewEvent.state"
              },
              "source": {
                "type": "str",
                "entity_field": "ReviewEvent.source"
              },
              "code": {
                "type": "str",
                "entity_field": "ReviewEvent.code"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "ReviewEvent",
              "operation": "read"
            }
          ]
        },
        "TriggerEvent": {
          "method_name": "TriggerEvent",
          "module": "ReviewEventTracking",
          "class": "ReviewEventTracker",
          "description": "Initiates review processing for the specified event (SRS use case: 触发代码审查执行). Updates the event state to begin the code review pipeline.",
          "type": "external_api",
          "http": {
            "verb": "POST",
            "route": "/api/events/{event_id}/trigger"
          },
          "input": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": "ReviewEvent.event_id",
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": "ReviewEvent.event_id"
              },
              "state": {
                "type": "enum",
                "entity_field": "ReviewEvent.state"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "ReviewEvent",
              "operation": "read"
            },
            {
              "entity": "ReviewEvent",
              "operation": "update"
            }
          ]
        },
        "UpdateEventState": {
          "method_name": "UpdateEventState",
          "module": "ReviewEventTracking",
          "class": "ReviewEventTracker",
          "description": "Updates the lifecycle state of a given review event. Ensures valid state transitions for subsequent handling in the review pipeline.",
          "type": "external_api",
          "http": {
            "verb": "POST",
            "route": "/api/events/{event_id}/update-state"
          },
          "input": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": "ReviewEvent.event_id",
                "required": true
              },
              "new_state": {
                "type": "enum",
                "entity_field": "ReviewEvent.state",
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": "ReviewEvent.event_id"
              },
              "state": {
                "type": "enum",
                "entity_field": "ReviewEvent.state"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "ReviewEvent",
              "operation": "read"
            },
            {
              "entity": "ReviewEvent",
              "operation": "update"
            }
          ]
        }
      }
    },
    "RuleManagement": {
      "description": "Provides CRUD management and validation for code review rules and prompts. It supplies active rules for usage in analysis pipelines, ensuring flexible and up-to-date checks (FR-006).",
      "entities": [
        "Rule"
      ],
      "methods": {
        "GetRules": {
          "method_name": "GetRules",
          "module": "RuleManagement",
          "class": "RuleManager",
          "description": "Retrieves the full list of existing code review rules (FR-006). Developers can view all configured rules to manage or apply them.",
          "type": "external_api",
          "http": {
            "verb": "GET",
            "route": "/api/rules"
          },
          "input": {
            "fields": {
            }
          },
          "output": {
            "fields": {
              "rules": {
                "type": "array",
                "entity_field": null
              }
            }
          },
          "entity_operations": [
            {
              "entity": "Rule",
              "operation": "read"
            }
          ]
        },
        "CreateRule": {
          "method_name": "CreateRule",
          "module": "RuleManagement",
          "class": "RuleManager",
          "description": "Creates a new custom code review rule (FR-006). Stores the rule data and sets its enabled status for immediate application in the analysis pipeline.",
          "type": "external_api",
          "http": {
            "verb": "POST",
            "route": "/api/rules"
          },
          "input": {
            "fields": {
              "enabled": {
                "type": "bool",
                "entity_field": "Rule.enabled",
                "required": true
              },
              "rule_data": {
                "type": "dict",
                "entity_field": "Rule.rule_data",
                "required": false
              }
            }
          },
          "output": {
            "fields": {
              "rule_id": {
                "type": "str",
                "entity_field": "Rule.rule_id"
              },
              "enabled": {
                "type": "bool",
                "entity_field": "Rule.enabled"
              },
              "rule_data": {
                "type": "dict",
                "entity_field": "Rule.rule_data"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "Rule",
              "operation": "create"
            }
          ]
        },
        "UpdateRule": {
          "method_name": "UpdateRule",
          "module": "RuleManagement",
          "class": "RuleManager",
          "description": "Updates the specified code review rule (FR-006). Allows modification of the rule's data or enabled status, ensuring ongoing alignment with project needs.",
          "type": "external_api",
          "http": {
            "verb": "PUT",
            "route": "/api/rules/{rule_id}"
          },
          "input": {
            "fields": {
              "rule_id": {
                "type": "str",
                "entity_field": "Rule.rule_id",
                "required": true
              },
              "enabled": {
                "type": "bool",
                "entity_field": "Rule.enabled",
                "required": true
              },
              "rule_data": {
                "type": "dict",
                "entity_field": "Rule.rule_data",
                "required": false
              }
            }
          },
          "output": {
            "fields": {
              "rule_id": {
                "type": "str",
                "entity_field": "Rule.rule_id"
              },
              "enabled": {
                "type": "bool",
                "entity_field": "Rule.enabled"
              },
              "rule_data": {
                "type": "dict",
                "entity_field": "Rule.rule_data"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "Rule",
              "operation": "read"
            },
            {
              "entity": "Rule",
              "operation": "update"
            }
          ]
        },
        "DeleteRule": {
          "method_name": "DeleteRule",
          "module": "RuleManagement",
          "class": "RuleManager",
          "description": "Removes an existing code review rule (FR-006). Frees resources and ensures outdated rules do not affect future analyses.",
          "type": "external_api",
          "http": {
            "verb": "DELETE",
            "route": "/api/rules/{rule_id}"
          },
          "input": {
            "fields": {
              "rule_id": {
                "type": "str",
                "entity_field": "Rule.rule_id",
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "success": {
                "type": "bool",
                "entity_field": null
              }
            }
          },
          "entity_operations": [
            {
              "entity": "Rule",
              "operation": "read"
            },
            {
              "entity": "Rule",
              "operation": "update"
            }
          ]
        }
      }
    },
    "CodeAnalysisEngine": {
      "description": "Acts as the core entry point for automated review pipelines, orchestrating sub-tasks and aggregating results. It integrates AI models to perform security, lint, and performance checks (FR-003).",
      "entities": [
        "ReviewEvent",
        "Report"
      ],
      "methods": {
        "RunPipeline": {
          "method_name": "RunPipeline",
          "module": "CodeAnalysisEngine",
          "class": "CodeAnalysisEngine",
          "description": "Orchestrates multiple analysis tasks for a specified event, aggregating results and creating a final Report entity (FR-003). This process collects sub-task outcomes into a comprehensive review output.",
          "type": "internal_function",
          "http": {
            "verb": null,
            "route": null
          },
          "input": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": "ReviewEvent.event_id",
                "required": true
              },
              "tasks": {
                "type": "array",
                "entity_field": null,
                "required": false
              }
            }
          },
          "output": {
            "fields": {
              "report_id": {
                "type": "str",
                "entity_field": "Report.report_id"
              },
              "status": {
                "type": "enum",
                "entity_field": "Report.status"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "ReviewEvent",
              "operation": "read"
            },
            {
              "entity": "Report",
              "operation": "create"
            }
          ]
        },
        "RunTask": {
          "method_name": "RunTask",
          "module": "CodeAnalysisEngine",
          "class": "CodeAnalysisEngine",
          "description": "Executes a single, specialized analysis task (security, lint, or performance) for the specified event, producing a new Report entity (FR-003).",
          "type": "internal_function",
          "http": {
            "verb": null,
            "route": null
          },
          "input": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": "ReviewEvent.event_id",
                "required": true
              },
              "task": {
                "type": "str",
                "entity_field": null,
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "report_id": {
                "type": "str",
                "entity_field": "Report.report_id"
              },
              "status": {
                "type": "enum",
                "entity_field": "Report.status"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "ReviewEvent",
              "operation": "read"
            },
            {
              "entity": "Report",
              "operation": "create"
            }
          ]
        }
      }
    },
    "AnalyzerIntegrators": {
      "description": "Provides specialized security, lint, and performance analysis capabilities invoked by the CodeAnalysisEngine for thorough coverage of potential code issues (FR-003).",
      "entities": [
        "Report"
      ],
      "methods": {
        "AnalyzeSecurity": {
          "method_name": "AnalyzeSecurity",
          "module": "AnalyzerIntegrators",
          "class": "AnalyzerIntegrator",
          "description": "Performs security analysis on the provided code and rule context (FR-003). Creates a new Report reflecting discovered vulnerabilities and status.",
          "type": "internal_function",
          "http": {
            "verb": null,
            "route": null
          },
          "input": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": null,
                "required": true
              },
              "code": {
                "type": "str",
                "entity_field": null,
                "required": true
              },
              "rule": {
                "type": "dict",
                "entity_field": null,
                "required": false
              }
            }
          },
          "output": {
            "fields": {
              "report_id": {
                "type": "str",
                "entity_field": "Report.report_id"
              },
              "status": {
                "type": "enum",
                "entity_field": "Report.status"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "Report",
              "operation": "create"
            }
          ]
        },
        "AnalyzeLint": {
          "method_name": "AnalyzeLint",
          "module": "AnalyzerIntegrators",
          "class": "AnalyzerIntegrator",
          "description": "Performs lint and style checks on the provided code and rule parameters (FR-003). Creates a new Report capturing the lint analysis results.",
          "type": "internal_function",
          "http": {
            "verb": null,
            "route": null
          },
          "input": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": null,
                "required": true
              },
              "code": {
                "type": "str",
                "entity_field": null,
                "required": true
              },
              "rule": {
                "type": "dict",
                "entity_field": null,
                "required": false
              }
            }
          },
          "output": {
            "fields": {
              "report_id": {
                "type": "str",
                "entity_field": "Report.report_id"
              },
              "status": {
                "type": "enum",
                "entity_field": "Report.status"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "Report",
              "operation": "create"
            }
          ]
        },
        "AnalyzePerformance": {
          "method_name": "AnalyzePerformance",
          "module": "AnalyzerIntegrators",
          "class": "AnalyzerIntegrator",
          "description": "Analyzes performance aspects of the provided code using the specified rule data (FR-003). Produces a new Report detailing performance bottlenecks and suggestions.",
          "type": "internal_function",
          "http": {
            "verb": null,
            "route": null
          },
          "input": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": null,
                "required": true
              },
              "code": {
                "type": "str",
                "entity_field": null,
                "required": true
              },
              "rule": {
                "type": "dict",
                "entity_field": null,
                "required": false
              }
            }
          },
          "output": {
            "fields": {
              "report_id": {
                "type": "str",
                "entity_field": "Report.report_id"
              },
              "status": {
                "type": "enum",
                "entity_field": "Report.status"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "Report",
              "operation": "create"
            }
          ]
        }
      }
    },
    "ReportingFeedback": {
      "description": "Stores and displays review outcomes, posting automated comments to GitLab and managing developer feedback. Supports creation and retrieval of review reports (FR-004, FR-007).",
      "entities": [
        "Report"
      ],
      "methods": {
        "GetReport": {
          "method_name": "GetReport",
          "module": "ReportingFeedback",
          "class": "ReportingFeedbackService",
          "description": "Retrieves the report associated with a specific event_id (FR-007). Allows developers to view the code review findings and recommendations.",
          "type": "external_api",
          "http": {
            "verb": "GET",
            "route": "/api/reports/{event_id}"
          },
          "input": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": "Report.event_id",
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "report_id": {
                "type": "str",
                "entity_field": "Report.report_id"
              },
              "event_id": {
                "type": "str",
                "entity_field": "Report.event_id"
              },
              "reprot_content": {
                "type": "str",
                "entity_field": "Report.reprot_content"
              },
              "status": {
                "type": "enum",
                "entity_field": "Report.status"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "Report",
              "operation": "read"
            }
          ]
        },
        "PostGitlabComment": {
          "method_name": "PostGitlabComment",
          "module": "ReportingFeedback",
          "class": "ReportingFeedbackService",
          "description": "Submits an automated comment on GitLab for the given report (FR-004). Reads the associated Report entity to ensure validity and posts the response to GitLab.",
          "type": "external_api",
          "http": {
            "verb": "POST",
            "route": "/api/reports/{event_id}/gitlab-comment"
          },
          "input": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": "Report.event_id",
                "required": true
              },
              "comment_data": {
                "type": "str",
                "entity_field": null,
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "comment_posted": {
                "type": "bool",
                "entity_field": null
              }
            }
          },
          "entity_operations": [
            {
              "entity": "Report",
              "operation": "read"
            }
          ]
        },
        "PostFeedback": {
          "method_name": "PostFeedback",
          "module": "ReportingFeedback",
          "class": "ReportingFeedbackService",
          "description": "Receives developer feedback for a given report (FR-007, FR-012). Reads the Report to confirm it exists, then stores the feedback externally or in the system logs.",
          "type": "external_api",
          "http": {
            "verb": "POST",
            "route": "/api/reports/{event_id}/feedback"
          },
          "input": {
            "fields": {
              "event_id": {
                "type": "str",
                "entity_field": "Report.event_id",
                "required": true
              },
              "feedback_data": {
                "type": "str",
                "entity_field": null,
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "feedback_stored": {
                "type": "bool",
                "entity_field": null
              }
            }
          },
          "entity_operations": [
            {
              "entity": "Report",
              "operation": "read"
            }
          ]
        }
      }
    },
    "AnalyticsStatistics": {
      "description": "Provides aggregated analytics and trends from review and feedback data (FR-008 to FR-011). Offers insights into acceptance rates, time-series, heatmaps, and review duration metrics.",
      "entities": [
        "Report"
      ],
      "methods": {
        "GetSummary": {
          "method_name": "GetSummary",
          "module": "AnalyticsStatistics",
          "class": "AnalyticsService",
          "description": "Computes a summary of review acceptance rates and key metrics (FR-008). Aggregates data from existing reports to give a high-level overview of code review outcomes.",
          "type": "external_api",
          "http": {
            "verb": "GET",
            "route": "/api/analytics/summary"
          },
          "input": {
            "fields": {
            }
          },
          "output": {
            "fields": {
              "summary": {
                "type": "dict",
                "entity_field": null
              }
            }
          },
          "entity_operations": [
            {
              "entity": "Report",
              "operation": "aggregate"
            }
          ]
        },
        "GetHeatmap": {
          "method_name": "GetHeatmap",
          "module": "AnalyticsStatistics",
          "class": "AnalyticsService",
          "description": "Generates a heatmap of common issues across all reports (FR-010). Aggregates review data to highlight frequently occurring code problems.",
          "type": "external_api",
          "http": {
            "verb": "GET",
            "route": "/api/analytics/heatmap"
          },
          "input": {
            "fields": {
            }
          },
          "output": {
            "fields": {
              "heatmap_data": {
                "type": "dict",
                "entity_field": null
              }
            }
          },
          "entity_operations": [
            {
              "entity": "Report",
              "operation": "aggregate"
            }
          ]
        },
        "GetTimeseries": {
          "method_name": "GetTimeseries",
          "module": "AnalyticsStatistics",
          "class": "AnalyticsService",
          "description": "Retrieves the time-series data of reported issues or code review trends (FR-009, FR-011). Aggregates historical reports to display how quality and duration metrics evolve over time.",
          "type": "external_api",
          "http": {
            "verb": "GET",
            "route": "/api/analytics/timeseries"
          },
          "input": {
            "fields": {
            }
          },
          "output": {
            "fields": {
              "timeseries_data": {
                "type": "list",
                "entity_field": null
              }
            }
          },
          "entity_operations": [
            {
              "entity": "Report",
              "operation": "aggregate"
            }
          ]
        },
        "SetReportDecision": {
          "method_name": "SetReportDecision",
          "module": "AnalyticsStatistics",
          "class": "AnalyticsService",
          "description": "Applies a user decision (e.g., accept or finalize) to a given report (FR-008). Updates the report status to reflect the final review outcome for analytics tracking.",
          "type": "external_api",
          "http": {
            "verb": "POST",
            "route": "/api/analytics/report/{report_id}/decision"
          },
          "input": {
            "fields": {
              "report_id": {
                "type": "str",
                "entity_field": "Report.report_id",
                "required": true
              },
              "decision": {
                "type": "enum",
                "entity_field": "Report.status",
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "report_id": {
                "type": "str",
                "entity_field": "Report.report_id"
              },
              "status": {
                "type": "enum",
                "entity_field": "Report.status"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "Report",
              "operation": "read"
            },
            {
              "entity": "Report",
              "operation": "update"
            }
          ]
        }
      }
    }
  }
}