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
          ],
          "trigger": "Invoked by external clients sending a GitLab webhook request.",
          "steps": [
            "1. Invoke ParseGitLabEvent to extract code from the incoming payload.",
            "2. Assign the extracted code to the new ReviewEvent along with a pending state and GitLab as the source.",
            "3. Finalize creation of the ReviewEvent record.",
            "4. Return the newly created event_id and state."
          ],
          "invoked_methods": [
            {
              "module": "WebhookEventIngestion",
              "method": "ParseGitLabEvent",
              "purpose": "Extract code from the payload for event creation"
            }
          ],
          "key_functional_points": [
            {
              "capability": "ReceiveExternalGitLabEvent",
              "description": "Must receive GitLab event as per FR-001 and create a new pending ReviewEvent triggered by the event’s content.",
              "source": "SRS: FR-001"
            },
            {
              "capability": "ExternalSourceValidation",
              "description": "Must parse the external event data to ensure it meets system requirements.",
              "source": "Plugin:A"
            },
            {
              "capability": "PayloadNormalizationAndExtraction",
              "description": "Must extract relevant code data from the webhook payload for event creation.",
              "source": "Plugin:A"
            },
            {
              "capability": "ContextConstruction",
              "description": "Associate extracted code with a newly created ReviewEvent in a pending state for further processing.",
              "source": "Plugin:A"
            }
          ],
          "external_api_calls": []
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
          ],
          "trigger": "Invoked by external clients or systems that manually send the trigger payload.",
          "steps": [
            "1. Invoke ParseManualEvent to extract code from the incoming payload.",
            "2. Assign the extracted code to the new ReviewEvent with a pending state and an appropriate source.",
            "3. Finalize creation of the ReviewEvent record.",
            "4. Return the newly created event_id and state."
          ],
          "invoked_methods": [
            {
              "module": "WebhookEventIngestion",
              "method": "ParseManualEvent",
              "purpose": "Extract code from the payload for event creation"
            }
          ],
          "key_functional_points": [
            {
              "capability": "ExternalEventReception",
              "description": "Must support manual external triggers to create a new pending ReviewEvent.",
              "source": "Plugin:A"
            },
            {
              "capability": "PayloadNormalizationAndExtraction",
              "description": "Must parse the payload and extract relevant code data.",
              "source": "Plugin:A"
            },
            {
              "capability": "ContextConstruction",
              "description": "Create a ReviewEvent, capturing code and source for subsequent analysis.",
              "source": "Plugin:A"
            }
          ],
          "external_api_calls": []
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
          ],
          "trigger": "Invoked by external clients or systems needing a list of pending events.",
          "steps": [
            "1. Load all ReviewEvent records with state set to pending.",
            "2. Return the list of pending events."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "ListPendingReviewEvents",
              "description": "Must provide the capability to retrieve events waiting for review.",
              "source": "SRS"
            }
          ],
          "external_api_calls": []
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
          ],
          "trigger": "Invoked by external clients or systems to view the event’s current data.",
          "steps": [
            "1. Retrieve the specified ReviewEvent by its ID.",
            "2. Return the event fields."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "RetrieveEventData",
              "description": "Must return the full details of a specified ReviewEvent.",
              "source": "SRS"
            }
          ],
          "external_api_calls": []
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
          ],
          "trigger": "Invoked by external clients or systems once an event is ready for analysis.",
          "steps": [
            "1. Retrieve the ReviewEvent by its ID.",
            "2. Adjust the event’s state or signals to initiate processing.",
            "3. Return a success indicator."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "InitiateReviewFlow",
              "description": "Must enable the developer to trigger code review execution for a specific event per use case ‘触发代码审查执行’.",
              "source": "SRS"
            }
          ],
          "external_api_calls": []
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
          ],
          "trigger": "Invoked by external clients or systems wanting to modify an event’s state for lifecycle progression.",
          "steps": [
            "1. Retrieve the ReviewEvent by its ID.",
            "2. Update the event’s state to the provided new_state.",
            "3. Return a success indicator."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "ManageEventLifecycle",
              "description": "Must allow event state to be updated in conformance with review lifecycle transitions.",
              "source": "SRS"
            }
          ],
          "external_api_calls": []
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
          ],
          "trigger": "Invoked by external clients or systems requiring an overview of all existing rules.",
          "steps": [
            "1. Load all available Rule entities.",
            "2. Return the list of rules."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "RetrieveAllRules",
              "description": "Must expose all system-defined code review rules for viewing or management per FR-006.",
              "source": "SRS: FR-006"
            }
          ],
          "external_api_calls": []
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
          ],
          "trigger": "Invoked by external clients or systems seeking to create a new rule.",
          "steps": [
            "1. Parse the incoming data for enabled status and rule configuration.",
            "2. Create a new Rule entity with the provided fields.",
            "3. Return the newly assigned rule_id."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "AddNewCustomRule",
              "description": "Must allow adding a new code review rule in compliance with FR-006.",
              "source": "SRS: FR-006"
            }
          ],
          "external_api_calls": []
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
          ],
          "trigger": "Invoked by external clients or systems adjusting an existing rule.",
          "steps": [
            "1. Retrieve the specified Rule entity using the rule_id.",
            "2. Update the entity’s enabled field or rule_data as provided.",
            "3. Return the existing rule_id."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "ModifyExistingCustomRule",
              "description": "Must support updating existing rule definitions in accordance with FR-006.",
              "source": "SRS: FR-006"
            }
          ],
          "external_api_calls": []
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
          ],
          "trigger": "Invoked by external clients or systems that need to remove a rule entirely.",
          "steps": [
            "1. Retrieve the specified Rule by its rule_id.",
            "2. Remove the rule from the system.",
            "3. Return a success indicator."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "DeleteCustomRule",
              "description": "Must permit complete removal of a specified rule to fulfill FR-006’s rule-management.",
              "source": "SRS: FR-006"
            }
          ],
          "external_api_calls": []
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
          ],
          "trigger": "Invoked by internal review workflows or triggers needing a full multi-task analysis pipeline.",
          "steps": [
            "1. Retrieve the specified ReviewEvent by event_id.",
            "2. Invoke GetActiveRules to obtain enabled rules for analysis.",
            "3. For each task in the tasks list, invoke RunTask with the event ID and task.",
            "4. Collect all sub-task results for aggregation.",
            "5. Create a new aggregated Report that consolidates the outcomes.",
            "6. Return the newly created report_id."
          ],
          "invoked_methods": [
            {
              "module": "RuleManagement",
              "method": "GetActiveRules",
              "purpose": "Obtain the currently enabled rules for analysis"
            },
            {
              "module": "CodeAnalysisEngine",
              "method": "RunTask",
              "purpose": "Execute each requested analysis sub-task"
            }
          ],
          "key_functional_points": [
            {
              "capability": "OrchestrateMultiTaskPipeline",
              "description": "Must coordinate multiple sub-tasks in a defined sequence to fulfill the automated code analysis per FR-003.",
              "source": "SRS: FR-003"
            },
            {
              "capability": "DeterministicExecutionOrder",
              "description": "Guarantee tasks run in a predictable sequence to accumulate results consistently.",
              "source": "Plugin:C"
            },
            {
              "capability": "AggregateResults",
              "description": "Combine outputs from all tasks into a unified report for further handling.",
              "source": "Plugin:C"
            }
          ],
          "external_api_calls": [
            {
              "api_name": "代码仓库接口",
              "operation": "获取最新代码及提交信息",
              "srs_requirement": "FR-002",
              "purpose": "Retrieve the latest code for subsequent analysis tasks",
              "data_direction": "send"
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
          ],
          "trigger": "Invoked by internal workflows or pipeline logic for an individual analysis sub-task.",
          "steps": [
            "1. Retrieve the specified ReviewEvent by event_id.",
            "2. Invoke GetActiveRules to obtain relevant rule data.",
            "3. Based on the task input, invoke the appropriate analysis method (AnalyzeSecurity, AnalyzeLint, or AnalyzePerformance).",
            "4. Create a new Report containing the analysis outcome.",
            "5. Return the newly created report_id."
          ],
          "invoked_methods": [
            {
              "module": "RuleManagement",
              "method": "GetActiveRules",
              "purpose": "Fetch currently enabled rules to guide the task analysis"
            },
            {
              "module": "AnalyzerIntegrators",
              "method": "AnalyzeSecurity",
              "purpose": "Perform security analysis on the code when task is security"
            },
            {
              "module": "AnalyzerIntegrators",
              "method": "AnalyzeLint",
              "purpose": "Perform lint analysis on the code when task is lint"
            },
            {
              "module": "AnalyzerIntegrators",
              "method": "AnalyzePerformance",
              "purpose": "Perform performance analysis on the code when task is performance"
            }
          ],
          "key_functional_points": [
            {
              "capability": "ExecuteIndividualAnalysisTask",
              "description": "Must run a single analysis sub-task using the relevant rule data to address FR-003.",
              "source": "SRS: FR-003"
            },
            {
              "capability": "TaskLevelOrchestration",
              "description": "Handle the invocation of sub-task methods in a single-step context.",
              "source": "Plugin:C"
            }
          ],
          "external_api_calls": []
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
          ],
          "trigger": "Invoked by the CodeAnalysisEngine as a sub-task when security analysis is required.",
          "steps": [
            "1. Read the event code using the provided event_id.",
            "2. Retrieve the relevant rule_data for security checks.",
            "3. Perform the security analysis logic.",
            "4. Return the analysis_result data."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "CodeSecurityEvaluation",
              "description": "Must detect potential vulnerabilities in the provided code as part of FR-003.",
              "source": "SRS: FR-003"
            },
            {
              "capability": "AIModelInvocationForSecurity",
              "description": "Use AI model for semantic security checks and produce structured findings.",
              "source": "Plugin:B"
            }
          ],
          "external_api_calls": [
            {
              "api_name": "AI 模型（GPT、Claude、Gemini）",
              "operation": "执行自动化代码分析",
              "srs_requirement": "FR-003",
              "purpose": "Perform automated security analysis using the AI model",
              "data_direction": "send"
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
          ],
          "trigger": "Invoked by the CodeAnalysisEngine as a sub-task when lint analysis is required.",
          "steps": [
            "1. Read the event code using the provided event_id.",
            "2. Retrieve the relevant rule_data for lint checks.",
            "3. Perform lint analysis on the code.",
            "4. Return the analysis_result data."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "LintComplianceCheck",
              "description": "Must detect style or formatting issues to fulfill FR-003 sub-task requirements.",
              "source": "SRS: FR-003"
            },
            {
              "capability": "AIModelInvocationForLint",
              "description": "Use AI model or rule-based logic to scan code for style and guideline violations.",
              "source": "Plugin:B"
            }
          ],
          "external_api_calls": [
            {
              "api_name": "AI 模型（GPT、Claude、Gemini）",
              "operation": "执行自动化代码分析",
              "srs_requirement": "FR-003",
              "purpose": "Perform lint and style checks using the AI model",
              "data_direction": "send"
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
          ],
          "trigger": "Invoked by the CodeAnalysisEngine as a sub-task when performance analysis is required.",
          "steps": [
            "1. Read the event code using the provided event_id.",
            "2. Retrieve the relevant rule_data for performance checks.",
            "3. Perform performance analysis on the code.",
            "4. Return the analysis_result data."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "PerformanceBottleneckIdentification",
              "description": "Must detect potential code performance issues as required by FR-003.",
              "source": "SRS: FR-003"
            },
            {
              "capability": "AIModelInvocationForPerformance",
              "description": "Utilize AI analysis for performance insights and optimization suggestions.",
              "source": "Plugin:B"
            }
          ],
          "external_api_calls": [
            {
              "api_name": "AI 模型（GPT、Claude、Gemini）",
              "operation": "执行自动化代码分析",
              "srs_requirement": "FR-003",
              "purpose": "Provide performance optimization suggestions using the AI model",
              "data_direction": "send"
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
          ],
          "trigger": "Invoked by external clients or systems requesting the event’s analysis results.",
          "steps": [
            "1. Identify all Report entries linked to the provided event_id.",
            "2. Return the retrieved reports."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "RetrieveEventReports",
              "description": "Must present the analysis outcomes for a specified event in compliance with FR-007.",
              "source": "SRS: FR-007"
            }
          ],
          "external_api_calls": []
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
          ],
          "trigger": "Invoked by an external client or system that wants to post an automated comment.",
          "steps": [
            "1. Retrieve the ReviewEvent by event_id to gather necessary context.",
            "2. Compile the comment data to match GitLab’s expected format.",
            "3. Send the comment to GitLab.",
            "4. Return a success indicator."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "AutomatedGitLabCommentSubmission",
              "description": "Must post review findings to GitLab MR/PR in compliance with FR-004.",
              "source": "SRS: FR-004"
            },
            {
              "capability": "ExternalSystemInteraction",
              "description": "Integrate with GitLab’s API to submit a comment without internal domain changes.",
              "source": "Plugin:D"
            }
          ],
          "external_api_calls": [
            {
              "api_name": "GitLab",
              "operation": "提交审查评论",
              "srs_requirement": "FR-004",
              "purpose": "Post the code review comment on the relevant MR/PR page",
              "data_direction": "send"
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
          ],
          "trigger": "Invoked by an external client or system providing feedback on a review event’s outcomes.",
          "steps": [
            "1. Locate the relevant Report entries associated with the given event_id.",
            "2. Append or update the feedback information in the targeted report.",
            "3. Return a success indicator."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "CaptureDeveloperFeedback",
              "description": "Must store the developer’s feedback regarding the review findings as per use case ‘提交审查问题反馈’.",
              "source": "SRS"
            }
          ],
          "external_api_calls": []
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
          ],
          "trigger": "Invoked by external clients or systems requesting an overview of aggregated analysis results.",
          "steps": [
            "1. Retrieve all relevant Report records.",
            "2. Compute the required summary metrics.",
            "3. Return the summary data."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "AggregateReviewMetrics",
              "description": "Must collect system-wide data (e.g., acceptance rate, average time) to align with FR-008 and FR-011.",
              "source": "SRS: FR-008, FR-011"
            },
            {
              "capability": "DataAggregationAndAnalysis",
              "description": "Perform data gathering across multiple reports to produce an overall summary for consumption.",
              "source": "Plugin:E"
            }
          ],
          "external_api_calls": []
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
            "fields": {}
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
          ],
          "trigger": "Invoked by external clients or systems wanting to visualize frequent problem areas from code review findings.",
          "steps": [
            "1. Retrieve relevant Report records.",
            "2. Process the data to identify issue concentration or distributions.",
            "3. Return the resulting heatmap data."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "GenerateIssueHeatmap",
              "description": "Must present common or frequent code problems in a heatmap format to satisfy FR-010.",
              "source": "SRS: FR-010"
            },
            {
              "capability": "StatisticalIssueDistribution",
              "description": "Aggregate historical issue data across multiple reports to highlight problem hotspots.",
              "source": "Plugin:E"
            }
          ],
          "external_api_calls": []
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
            "fields": {}
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
          ],
          "trigger": "Invoked by external clients or systems needing chronological trends from review analysis.",
          "steps": [
            "1. Retrieve the relevant Report records.",
            "2. Calculate trends or metrics over time from the reports.",
            "3. Return the timeseries data."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "CodeReviewTrendAnalysis",
              "description": "Must produce historical changes in issue counts or metrics to address FR-009.",
              "source": "SRS: FR-009"
            },
            {
              "capability": "TimeSeriesComputation",
              "description": "Aggregate data over chronological intervals for trending insights.",
              "source": "Plugin:E"
            }
          ],
          "external_api_calls": []
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
          ],
          "trigger": "Invoked by external clients or systems that finalize the usage or outcome of a particular report.",
          "steps": [
            "1. Retrieve the specified Report by its report_id.",
            "2. Update the report to reflect the final decision, such as a changed status.",
            "3. Return a success indicator."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "FinalizeReportOutcome",
              "description": "Must record the developer’s acceptance or rejection for the report, supporting FR-008 acceptance rate tracking.",
              "source": "SRS: FR-008"
            }
          ],
          "external_api_calls": []
        }
      }
    }
  }
}