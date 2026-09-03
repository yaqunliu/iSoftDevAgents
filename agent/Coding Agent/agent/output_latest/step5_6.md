{
  "backend": {
    "run.py": {
      "priority": 43,
      "description": "Flask runner script.",
      "source_ref": null,
      "depends_on": [
        "app/__init__.py"
      ]
    },
    "app": {
      "__init__.py": {
        "priority": 42,
        "description": "Application entry point initialization.",
        "source_ref": null,
        "depends_on": [
          "app/api/__init__.py",
          "app/config.py"
        ]
      },
      "config.py": {
        "priority": 1,
        "description": "Application configuration settings.",
        "source_ref": null,
        "depends_on": []
      },
      "extensions.py": {
        "priority": 2,
        "description": "Extensions and third-party integrations.",
        "source_ref": null,
        "depends_on": []
      },
      "api": {
        "__init__.py": {
          "priority": 41,
          "description": "Aggregator for all API modules.",
          "source_ref": null,
          "depends_on": [
            "app/api/analytics_statistics_api.py",
            "app/api/analyzer_integrators_api.py",
            "app/api/code_analysis_engine_api.py",
            "app/api/reporting_feedback_api.py",
            "app/api/review_event_tracking_api.py",
            "app/api/rule_management_api.py",
            "app/api/webhook_event_ingestion_api.py"
          ]
        },
        "analytics_statistics_api.py": {
          "priority": 40,
          "description": "This module offers aggregated metrics and statistics derived from existing reports. It provides capabilities like summary data, issue heatmaps, and time-series analysis. By capturing final decisions on reports, it helps track acceptance rates and evolving trends, supporting data-driven improvements to the code review process.",
          "source_ref": [
            "backend.modules.AnalyticsStatistics"
          ],
          "depends_on": [
            "app/services/analytics_statistics_service.py"
          ]
        },
        "analyzer_integrators_api.py": {
          "priority": 40,
          "description": "This module provides specialized analysis capabilities for security, lint, and performance checks. It populates new reports with findings to ensure comprehensive coverage of potential code issues. Each method uses relevant rule data or AI-based logic to identify vulnerabilities and improvement opportunities, assisting the automated review pipeline.",
          "source_ref": [
            "backend.modules.AnalyzerIntegrators"
          ],
          "depends_on": [
            "app/services/analyzer_integrators_service.py"
          ]
        },
        "code_analysis_engine_api.py": {
          "priority": 40,
          "description": "This module orchestrates the execution of multiple analysis tasks to produce a consolidated report. It coordinates each sub-task, including retrieving event data, gathering active rules, and integrating analysis results. By running either an entire pipeline or a single task, it forms the core of the system’s automated review workflow.",
          "source_ref": [
            "backend.modules.CodeAnalysisEngine"
          ],
          "depends_on": [
            "app/services/code_analysis_engine_service.py"
          ]
        },
        "reporting_feedback_api.py": {
          "priority": 40,
          "description": "This module centralizes the retrieval of review reports and the submission of feedback or automated comments. It ensures that developers can easily view analysis outcomes and provide additional insights. By bridging the gap between the system’s review data and external feedback channels, it supports both GitLab interactions and internal logging.",
          "source_ref": [
            "backend.modules.ReportingFeedback"
          ],
          "depends_on": [
            "app/services/reporting_feedback_service.py"
          ]
        },
        "review_event_tracking_api.py": {
          "priority": 40,
          "description": "This module manages the lifecycle and state transitions of review events. It allows querying of pending events, retrieving specific event data, and triggering or updating their progress. By providing endpoints for these operations, it integrates with the broader analysis pipeline to manage the flow of events from creation to completion.",
          "source_ref": [
            "backend.modules.ReviewEventTracking"
          ],
          "depends_on": [
            "app/services/review_event_tracking_service.py"
          ]
        },
        "rule_management_api.py": {
          "priority": 40,
          "description": "This module handles the creation, retrieval, updating, and deletion of code review rules. It enables flexible management for rule data and statuses, ensuring relevant checks are applied during analysis. By exposing these operations, it guarantees the system remains current with evolving project requirements.",
          "source_ref": [
            "backend.modules.RuleManagement"
          ],
          "depends_on": [
            "app/services/rule_management_service.py"
          ]
        },
        "webhook_event_ingestion_api.py": {
          "priority": 40,
          "description": "This module focuses on ingesting external triggers, whether from GitLab webhooks or manual sources. It orchestrates data extraction and validation for new code submissions, ensuring each receives a pending ReviewEvent. Through these operations, it initiates the system’s review lifecycle by capturing relevant context for subsequent analysis.",
          "source_ref": [
            "backend.modules.WebhookEventIngestion"
          ],
          "depends_on": [
            "app/services/webhook_event_ingestion_service.py"
          ]
        }
      },
      "models": {
        "__init__.py": {
          "priority": 11,
          "description": "Central aggregator for all model files.",
          "source_ref": null,
          "depends_on": [
            "app/models/report.py",
            "app/models/review_event.py",
            "app/models/rule.py"
          ]
        },
        "report.py": {
          "priority": 10,
          "description": "Data model for Report entity.",
          "source_ref": [
            "data_model.entities.Report",
            "data_model.entities.ReviewEvent"
          ],
          "depends_on": []
        },
        "review_event.py": {
          "priority": 10,
          "description": "Data model for ReviewEvent entity.",
          "source_ref": [
            "data_model.entities.ReviewEvent",
            "data_model.entities.Report"
          ],
          "depends_on": []
        },
        "rule.py": {
          "priority": 10,
          "description": "Data model for Rule entity.",
          "source_ref": [
            "data_model.entities.Rule"
          ],
          "depends_on": []
        }
      },
      "repositories": {
        "report_repository.py": {
          "priority": 20,
          "description": "Repository for Report entity.",
          "source_ref": [
            "data_model.entities.Report.repository"
          ],
          "depends_on": [
            "app/models/report.py"
          ]
        },
        "review_event_repository.py": {
          "priority": 20,
          "description": "Repository for ReviewEvent entity.",
          "source_ref": [
            "data_model.entities.ReviewEvent.repository"
          ],
          "depends_on": [
            "app/models/review_event.py"
          ]
        },
        "rule_repository.py": {
          "priority": 20,
          "description": "Repository for Rule entity.",
          "source_ref": [
            "data_model.entities.Rule.repository"
          ],
          "depends_on": [
            "app/models/rule.py"
          ]
        }
      },
      "services": {
        "analytics_statistics_service.py": {
          "priority": 30,
          "description": "This module offers aggregated metrics and statistics derived from existing reports. It provides capabilities like summary data, issue heatmaps, and time-series analysis. By capturing final decisions on reports, it helps track acceptance rates and evolving trends, supporting data-driven improvements to the code review process.",
          "source_ref": [
            "backend.modules.AnalyticsStatistics"
          ],
          "depends_on": [
            "app/models/report.py",
            "app/repositories/report_repository.py"
          ]
        },
        "analyzer_integrators_service.py": {
          "priority": 30,
          "description": "This module provides specialized analysis capabilities for security, lint, and performance checks. It populates new reports with findings to ensure comprehensive coverage of potential code issues. Each method uses relevant rule data or AI-based logic to identify vulnerabilities and improvement opportunities, assisting the automated review pipeline.",
          "source_ref": [
            "backend.modules.AnalyzerIntegrators"
          ],
          "depends_on": [
            "app/models/report.py",
            "app/repositories/report_repository.py",
            "app/models/review_event.py",
            "app/repositories/review_event_repository.py"
          ]
        },
        "code_analysis_engine_service.py": {
          "priority": 31,
          "description": "This module orchestrates the execution of multiple analysis tasks to produce a consolidated report. It coordinates each sub-task, including retrieving event data, gathering active rules, and integrating analysis results. By running either an entire pipeline or a single task, it forms the core of the system’s automated review workflow.",
          "source_ref": [
            "backend.modules.CodeAnalysisEngine"
          ],
          "depends_on": [
            "app/models/review_event.py",
            "app/repositories/review_event_repository.py",
            "app/models/report.py",
            "app/repositories/report_repository.py",
            "app/services/rule_management_service.py",
            "app/services/analyzer_integrators_service.py"
          ]
        },
        "reporting_feedback_service.py": {
          "priority": 30,
          "description": "This module centralizes the retrieval of review reports and the submission of feedback or automated comments. It ensures that developers can easily view analysis outcomes and provide additional insights. By bridging the gap between the system’s review data and external feedback channels, it supports both GitLab interactions and internal logging.",
          "source_ref": [
            "backend.modules.ReportingFeedback"
          ],
          "depends_on": [
            "app/models/report.py",
            "app/repositories/report_repository.py",
            "app/models/review_event.py",
            "app/repositories/review_event_repository.py"
          ]
        },
        "review_event_tracking_service.py": {
          "priority": 30,
          "description": "This module manages the lifecycle and state transitions of review events. It allows querying of pending events, retrieving specific event data, and triggering or updating their progress. By providing endpoints for these operations, it integrates with the broader analysis pipeline to manage the flow of events from creation to completion.",
          "source_ref": [
            "backend.modules.ReviewEventTracking"
          ],
          "depends_on": [
            "app/models/review_event.py",
            "app/repositories/review_event_repository.py"
          ]
        },
        "rule_management_service.py": {
          "priority": 30,
          "description": "This module handles the creation, retrieval, updating, and deletion of code review rules. It enables flexible management for rule data and statuses, ensuring relevant checks are applied during analysis. By exposing these operations, it guarantees the system remains current with evolving project requirements.",
          "source_ref": [
            "backend.modules.RuleManagement"
          ],
          "depends_on": [
            "app/models/rule.py",
            "app/repositories/rule_repository.py"
          ]
        },
        "webhook_event_ingestion_service.py": {
          "priority": 30,
          "description": "This module focuses on ingesting external triggers, whether from GitLab webhooks or manual sources. It orchestrates data extraction and validation for new code submissions, ensuring each receives a pending ReviewEvent. Through these operations, it initiates the system’s review lifecycle by capturing relevant context for subsequent analysis.",
          "source_ref": [
            "backend.modules.WebhookEventIngestion"
          ],
          "depends_on": [
            "app/models/review_event.py",
            "app/repositories/review_event_repository.py"
          ]
        }
      },
      "utils": {},
      "tasks": {}
    }
  }
}