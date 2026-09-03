{
  "modules": {
    "WebhookEventIngestion": {
      "description": "Receives and processes inbound GitLab webhooks, initiating the review lifecycle as needed. The module also offers APIs for manual event triggering. In line with FR-001, it triggers the automated code review pipeline whenever new commits or merge requests occur.",
      "entities": ["ReviewEvent"],
      "methods": {
        "HandleGitLabWebhook": {
          "method_name": "HandleGitLabWebhook",
          "module": "WebhookEventIngestion",
          "class": "EventIngestionController",
          "description": "Receives a GitLab webhook payload and creates a new ReviewEvent (FR-001). Validates the payload and triggers the code review lifecycle for the event.",
          "type": "external_api",
          "http": {
            "verb": "POST",
            "route": "/api/webhook/gitlab"
          },
          "input": {
            "fields": {
              "payload": {
                "type": "json",
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
          "description": "Accepts a manual event payload from external clients. Creates a new ReviewEvent and starts its review lifecycle, as indicated by Domain.md.",
          "type": "external_api",
          "http": {
            "verb": "POST",
            "route": "/api/event/manual-trigger"
          },
          "input": {
            "fields": {
              "payload": {
                "type": "json",
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
      "description": "Coordinates the entire code review event lifecycle, from creation to final state. Provides endpoints for querying event status and triggering analysis, in line with SRS use cases for selecting pending events or triggering code reviews.",
      "entities": ["ReviewEvent"],
      "methods": {
        "GetPendingEvents": {
          "method_name": "GetPendingEvents",
          "module": "ReviewEventTracking",
          "class": "ReviewEventTracker",
          "description": "Retrieves all pending ReviewEvent entries for developer selection (SRS use cases). Allows browsing of events waiting for review actions.",
          "type": "external_api",
          "http": {
            "verb": "GET",
            "route": "/api/events/pending"
          },
          "input": {
            "fields": {}
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
          "description": "Fetches details of a specific ReviewEvent by event_id. Supports SRS use case of selecting or viewing an event’s details.",
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
          "description": "Initiates the code review process for the specified event (SRS use case: 触发代码审查执行). Updates the event state and orchestrates analysis.",
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
              "new_state": {
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
          "description": "Updates the state field of a specific event to a new valid state (SRS lifecycle management). Helps control the event’s progress or finalization.",
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
              "updated_state": {
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
      "description": "Provides full CRUD capabilities for code review rules. Developers can define, modify, or remove custom rules in line with the SRS. Validates rules for correct format and logic.",
      "entities": ["Rule"],
      "methods": {
        "GetRules": {
          "method_name": "GetRules",
          "module": "RuleManagement",
          "class": "RuleManager",
          "description": "Retrieves the full list of code review rules (FR-006). Lets developers list existing rules for potential use in AI-based checks.",
          "type": "external_api",
          "http": {
            "verb": "GET",
            "route": "/api/rules"
          },
          "input": {
            "fields": {}
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
          "description": "Creates a new code review rule (FR-006). Stores the rule with specified enablement and data for custom analysis logic.",
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
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "rule_id": {
                "type": "str",
                "entity_field": "Rule.rule_id"
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
          "description": "Updates an existing rule’s details (FR-006). Modifies enablement or rule data by ID.",
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
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "rule_id": {
                "type": "str",
                "entity_field": "Rule.rule_id"
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
          "description": "Removes an existing rule by ID (FR-006). After deletion, the rule is no longer applied to future code analyses.",
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
            "fields": {}
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
        "GetActiveRules": {
          "method_name": "GetActiveRules",
          "module": "RuleManagement",
          "class": "RuleManager",
          "description": "Retrieves all currently enabled rules for internal usage (FR-003 references rule consumption by the AI pipeline).",
          "type": "internal_function",
          "http": {
            "verb": null,
            "route": null
          },
          "input": {
            "fields": {}
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
        }
      }
    },
    "CodeAnalysisEngine": {
      "description": "Acts as the core entry point for initiating automated code analysis pipelines. Coordinates tasks outlined in the SRS, retrieving rules from RuleManagement and creating reports in ReportingFeedback.",
      "entities": ["ReviewEvent", "Rule", "Report"],
      "methods": {
        "RunPipeline": {
          "method_name": "RunPipeline",
          "module": "CodeAnalysisEngine",
          "class": "CodeAnalysisEngine",
          "description": "Executes the full AI-based code analysis pipeline (FR-003). Reads the event and active rules, runs sub-tasks, and creates Reports with aggregated findings.",
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
                "type": "list",
                "entity_field": null,
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "result": {
                "type": "dict",
                "entity_field": null
              }
            }
          },
          "entity_operations": [
            {
              "entity": "ReviewEvent",
              "operation": "read"
            },
            {
              "entity": "Rule",
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
          "description": "Runs a single analysis task (FR-003). Reads the event and rules to produce a new Report for the specified task.",
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
              }
            }
          },
          "entity_operations": [
            {
              "entity": "ReviewEvent",
              "operation": "read"
            },
            {
              "entity": "Rule",
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
      "description": "Implements specialized AI-based code analysis tasks (security, lint, performance). Each method synchronously produces a Report.",
      "entities": ["ReviewEvent", "Rule", "Report"],
      "methods": {
        "AnalyzeSecurity": {
          "method_name": "AnalyzeSecurity",
          "module": "AnalyzerIntegrators",
          "class": "AnalyzerIntegrator",
          "description": "Performs the security analysis portion of FR-003. Reads event code and rules, generating a new security-oriented Report.",
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
              "code": {
                "type": "str",
                "entity_field": "ReviewEvent.code",
                "required": true
              },
              "rule_id": {
                "type": "str",
                "entity_field": "Rule.rule_id",
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "report_id": {
                "type": "str",
                "entity_field": "Report.report_id"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "ReviewEvent",
              "operation": "read"
            },
            {
              "entity": "Rule",
              "operation": "read"
            },
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
          "description": "Performs lint and style checks as part of FR-003. Reads event code, applies relevant rule data, and creates a new lint-focused Report.",
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
              "code": {
                "type": "str",
                "entity_field": "ReviewEvent.code",
                "required": true
              },
              "rule_id": {
                "type": "str",
                "entity_field": "Rule.rule_id",
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "report_id": {
                "type": "str",
                "entity_field": "Report.report_id"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "ReviewEvent",
              "operation": "read"
            },
            {
              "entity": "Rule",
              "operation": "read"
            },
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
          "description": "Performs performance analysis tasks under FR-003. Reads event code, applies performance rules, and returns a new Report.",
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
              "code": {
                "type": "str",
                "entity_field": "ReviewEvent.code",
                "required": true
              },
              "rule_id": {
                "type": "str",
                "entity_field": "Rule.rule_id",
                "required": true
              }
            }
          },
          "output": {
            "fields": {
              "report_id": {
                "type": "str",
                "entity_field": "Report.report_id"
              }
            }
          },
          "entity_operations": [
            {
              "entity": "ReviewEvent",
              "operation": "read"
            },
            {
              "entity": "Rule",
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
    "ReportingFeedback": {
      "description": "Collects and stores code review results, generating comprehensive reports for developer consumption. Automates the posting of code review comments to GitLab merge requests and enables developer feedback.",
      "entities": ["Report"],
      "methods": {
        "GetReport": {
          "method_name": "GetReport",
          "module": "ReportingFeedback",
          "class": "ReportingFeedbackService",
          "description": "Retrieves report(s) by event_id for developer viewing (FR-007). Allows inspection of the code review findings linked to the event.",
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
              "reports": {
                "type": "array",
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
        "PostGitLabComment": {
          "method_name": "PostGitLabComment",
          "module": "ReportingFeedback",
          "class": "ReportingFeedbackService",
          "description": "Posts a code review comment to GitLab referencing the specified event’s report (FR-004). Reads the report data then submits the comment externally.",
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
            "fields": {}
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
          "description": "Submits developer feedback on the event’s report (FR-012). Updates the report content or status if needed, storing the feedback in the system.",
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
              "report_id": {
                "type": "str",
                "entity_field": "Report.report_id"
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
    },
    "AnalyticsStatistics": {
      "description": "Aggregates historical code review data for efficiency, quality trends, and frequent issues. Offers summary, heatmap, timeseries, and decision endpoints per the SRS.",
      "entities": ["Report"],
      "methods": {
        "GetSummary": {
          "method_name": "GetSummary",
          "module": "AnalyticsStatistics",
          "class": "AnalyticsService",
          "description": "Generates an aggregated analytics summary (FR-008). Computes acceptance or improvement metrics from stored reports for a high-level overview.",
          "type": "external_api",
          "http": {
            "verb": "GET",
            "route": "/api/analytics/summary"
          },
          "input": {
            "fields": {}
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
          "description": "Creates a heatmap of common issues from the review data (FR-010). Aggregates historical Reports to identify frequently encountered problems.",
          "type": "external_api",
          "http": {
            "verb": "GET",
            "route": "/api/analytics/heatmap"
          },
          "input": {
            "fields": {}
          },
          "output": {
            "fields": {
              "heatmap": {
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
          "description": "Retrieves time-based analytics on review issues or performance (FR-009, FR-011). Aggregates Reports to display trends over specified intervals.",
          "type": "external_api",
          "http": {
            "verb": "GET",
            "route": "/api/analytics/timeseries"
          },
          "input": {
            "fields": {}
          },
          "output": {
            "fields": {
              "timeseries": {
                "type": "array",
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
          "description": "Applies a developer’s accept/reject decision to a specific report for finalizing analytics usage. Updates the status field as per the domain’s feedback logic.",
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
                "type": "str",
                "entity_field": null,
                "required": true
              }
            }
          },
          "output": {
            "fields": {
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