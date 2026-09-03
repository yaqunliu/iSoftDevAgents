{
  "modules": {
    "WebhookEventIngestion": {
      "description": "Receives and processes inbound GitLab webhooks, initiating the review lifecycle as needed. The module also offers APIs for manual event triggering. In line with FR-001, it triggers the automated code review pipeline whenever new commits or merge requests occur.",
      "entities": [
        "ReviewEvent"
      ],
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
          ],
          "trigger": "HTTP POST /api/webhook/gitlab from GitLab upon commit or MR creation.",
          "steps": [
            "Step1: Validate the webhook payload to ensure authenticity and well-formed data.",
            "Step2: Parse the incoming payload and extract event-specific code data.",
            "Step3: Create a new ReviewEvent record with state='pending', storing the parsed information.",
            "Step4: Immediately initiate the code review lifecycle by calling TriggerEvent on the newly created event."
          ],
          "invoked_methods": [
            {
              "module": "ReviewEventTracking",
              "method": "TriggerEvent",
              "purpose": "Begin code review pipeline for newly created event."
            }
          ],
          "key_functional_points": [
            {
              "capability": "ExternalSourceValidation",
              "description": "Validate and trust-check the GitLab payload to ensure authenticity.",
              "source": "Plugin:ExternalEventIngestion"
            },
            {
              "capability": "EventTypeIdentification",
              "description": "Identify the commit or MR creation event type from the payload.",
              "source": "Plugin:ExternalEventIngestion"
            },
            {
              "capability": "PayloadExtraction",
              "description": "Extract code references and relevant details from the webhook data.",
              "source": "Plugin:ExternalEventIngestion"
            },
            {
              "capability": "CreateReviewEvent",
              "description": "Create a new event record according to FR-001 requirements.",
              "source": "SRS"
            },
            {
              "capability": "ImmediatePipelineTrigger",
              "description": "Trigger the code review lifecycle immediately upon webhook reception.",
              "source": "SRS"
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
          ],
          "trigger": "HTTP POST /api/event/manual-trigger from external or ad-hoc clients.",
          "steps": [
            "Step1: Validate the incoming request to ensure it includes valid event data.",
            "Step2: Parse the payload for necessary code references and metadata.",
            "Step3: Create a new ReviewEvent with state='pending'.",
            "Step4: Immediately initiate the code review lifecycle by calling TriggerEvent with the new event_id."
          ],
          "invoked_methods": [
            {
              "module": "ReviewEventTracking",
              "method": "TriggerEvent",
              "purpose": "Begin code review pipeline for newly created event."
            }
          ],
          "key_functional_points": [
            {
              "capability": "ExternalSourceValidation",
              "description": "Validate manual trigger authenticity and payload structure.",
              "source": "Plugin:ExternalEventIngestion"
            },
            {
              "capability": "PayloadExtraction",
              "description": "Extract event details for code review from the request data.",
              "source": "Plugin:ExternalEventIngestion"
            },
            {
              "capability": "CreateReviewEvent",
              "description": "Create a new pending event record for manual triggers.",
              "source": "SRS"
            },
            {
              "capability": "ImmediatePipelineTrigger",
              "description": "Trigger code review lifecycle upon manual event creation.",
              "source": "SRS"
            }
          ]
        }
      }
    },
    "ReviewEventTracking": {
      "description": "Coordinates the entire code review event lifecycle, from creation to final state. Provides endpoints for querying event status and triggering analysis, in line with SRS use cases for selecting pending events or triggering code reviews.",
      "entities": [
        "ReviewEvent"
      ],
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
          ],
          "trigger": "HTTP GET /api/events/pending is called by a developer or client.",
          "steps": [
            "Step1: Retrieve all events with state='pending' from the internal store.",
            "Step2: Return the list of pending events to the caller."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "ListPendingReviewEvents",
              "description": "Expose pending events as described in the use case for developer selection.",
              "source": "SRS"
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
          ],
          "trigger": "HTTP GET /api/events/{event_id} with a valid event_id parameter.",
          "steps": [
            "Step1: Retrieve the event record by event_id from the internal store.",
            "Step2: Return the event details (state, source, code) to the caller."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "ReadReviewEventDetails",
              "description": "Provide the full event data so that the developer can inspect it.",
              "source": "SRS"
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
          ],
          "trigger": "HTTP POST /api/events/{event_id}/trigger is called by a developer or system component with an event_id.",
          "steps": [
            "Step1: Retrieve the specified ReviewEvent from storage.",
            "Step2: Update the ReviewEvent state to 'running', indicating analysis has started.",
            "Step3: Invoke RunPipeline within CodeAnalysisEngine, passing the event_id and the set of tasks (security, lint, performance).",
            "Step4: Upon completion or error, the ReviewEvent state is updated accordingly (completed or failed)."
          ],
          "invoked_methods": [
            {
              "module": "CodeAnalysisEngine",
              "method": "RunPipeline",
              "purpose": "Execute the multi-step AI-based analysis pipeline for the event."
            }
          ],
          "key_functional_points": [
            {
              "capability": "ReviewEventStateTransition",
              "description": "Transition the event state from 'pending' to 'running' and finalize post-analysis state.",
              "source": "SRS"
            },
            {
              "capability": "MultiStepAnalysisTrigger",
              "description": "Invoke the pipeline to perform security, lint, and performance tasks in a single flow.",
              "source": "Plugin:MultiStepOrPipelineOrientedExecution"
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
          ],
          "trigger": "HTTP POST /api/events/{event_id}/update-state with a desired new_state.",
          "steps": [
            "Step1: Retrieve the ReviewEvent by event_id from storage.",
            "Step2: Validate the provided new_state for correctness.",
            "Step3: Update the state field of the ReviewEvent and persist the change."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "ReviewEventStateManagement",
              "description": "Allow authorized clients to set the event to the next valid state, e.g., from 'running' to 'completed'.",
              "source": "SRS"
            }
          ]
        }
      }
    },
    "RuleManagement": {
      "description": "Provides full CRUD capabilities for code review rules. Developers can define, modify, or remove custom rules in line with the SRS. Validates rules for correct format and logic.",
      "entities": [
        "Rule"
      ],
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
          ],
          "trigger": "HTTP GET /api/rules is called by a developer or system component.",
          "steps": [
            "Step1: Fetch all Rule records from the system’s rule store.",
            "Step2: Return the list of rules."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "ListExistingRules",
              "description": "Provide a comprehensive set of current rules for developer review or modification.",
              "source": "SRS"
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
          ],
          "trigger": "HTTP POST /api/rules is called with rule data by a developer.",
          "steps": [
            "Step1: Validate the incoming rule data (enablement, rule_data structure).",
            "Step2: Create and store a new Rule record in the system’s rule store.",
            "Step3: Return the newly assigned rule_id to the caller."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "CreateCustomRule",
              "description": "Enable developers to define new code analysis rules consistent with FR-006.",
              "source": "SRS"
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
          ],
          "trigger": "HTTP PUT /api/rules/{rule_id} is called by a developer with updated rule data.",
          "steps": [
            "Step1: Retrieve the specified Rule by rule_id from the rule store.",
            "Step2: Validate the updated rule data.",
            "Step3: Overwrite the existing rule settings with the new data and persist the changes.",
            "Step4: Return the rule_id to confirm successful update."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "EditExistingRule",
              "description": "Allow developers to update an existing rule’s properties, fulfilling FR-006 for customizing or adjusting rules.",
              "source": "SRS"
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
          ],
          "trigger": "HTTP DELETE /api/rules/{rule_id} with a valid rule_id.",
          "steps": [
            "Step1: Retrieve the specified Rule by rule_id from the rule store.",
            "Step2: Remove the rule entry from the rule store, ensuring it is no longer used.",
            "Step3: Return success acknowledgement."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "RemoveCustomRule",
              "description": "Enable developers to delete a custom rule as part of FR-006 domain scope.",
              "source": "SRS"
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
          ],
          "trigger": "Called internally by the analysis engine or modules requiring the set of active rules.",
          "steps": [
            "Step1: Query the rule store for all enabled rules.",
            "Step2: Return the filtered set to the caller."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "ProvideEnabledRules",
              "description": "Offer only enabled rules for use in code analyses, supporting FR-003 referencing rule usage.",
              "source": "SRS"
            }
          ]
        }
      }
    },
    "CodeAnalysisEngine": {
      "description": "Acts as the core entry point for initiating automated code analysis pipelines. Coordinates tasks outlined in the SRS, retrieving rules from RuleManagement and creating reports in ReportingFeedback.",
      "entities": [
        "ReviewEvent",
        "Rule",
        "Report"
      ],
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
          ],
          "trigger": "Called internally any time a code review pipeline is initiated by the system (e.g., via TriggerEvent).",
          "steps": [
            "Step1: Read the ReviewEvent data to confirm state and retrieve code content.",
            "Step2: Retrieve active rules from RuleManagement.",
            "Step3: For each task in the provided tasks list, invoke RunTask with the event_id and the task.",
            "Step4: Aggregate all sub-task reports into a final outcome or data structure.",
            "Step5: Create or update a consolidated result record (e.g., a summary report)."
          ],
          "invoked_methods": [
            {
              "module": "CodeAnalysisEngine",
              "method": "RunTask",
              "purpose": "Perform an individual AI-based analysis sub-task (security, lint, or performance)."
            }
          ],
          "key_functional_points": [
            {
              "capability": "MultiTaskOrchestration",
              "description": "Coordinate multiple sub-tasks in a deterministic sequence for a single event.",
              "source": "Plugin:MultiStepOrPipelineOrientedExecution"
            },
            {
              "capability": "AIModelInvocationCoordination",
              "description": "Ensure each sub-task can leverage AI-based checks in line with FR-003 requirements.",
              "source": "Plugin:AI/LLMInvocation"
            },
            {
              "capability": "ResultAggregation",
              "description": "Combine outputs from each sub-task into a final pipeline result for further reporting.",
              "source": "SRS"
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
          ],
          "trigger": "Called internally by RunPipeline or other orchestrators specifying the target sub-task.",
          "steps": [
            "Step1: Retrieve the ReviewEvent data (including code) based on event_id.",
            "Step2: Retrieve the relevant set of active rules from RuleManagement.",
            "Step3: Determine the correct analyzer method (AnalyzeSecurity, AnalyzeLint, or AnalyzePerformance) based on the task parameter.",
            "Step4: Invoke the specified analyzer method and capture its report output.",
            "Step5: Persist or return the resulting report data to the caller."
          ],
          "invoked_methods": [
            {
              "module": "AnalyzerIntegrators",
              "method": "AnalyzeSecurity",
              "purpose": "Perform AI-driven security checks on the code."
            },
            {
              "module": "AnalyzerIntegrators",
              "method": "AnalyzeLint",
              "purpose": "Perform AI-driven lint/style checks on the code."
            },
            {
              "module": "AnalyzerIntegrators",
              "method": "AnalyzePerformance",
              "purpose": "Perform AI-driven performance analysis on the code."
            }
          ],
          "key_functional_points": [
            {
              "capability": "SingleTaskExecution",
              "description": "Perform one specialized analysis task for a targeted sub-area (security, lint, or performance).",
              "source": "SRS"
            },
            {
              "capability": "AIModelInvocation",
              "description": "Construct specialized input for the AI model and parse the returned analysis results.",
              "source": "Plugin:AI/LLMInvocation"
            }
          ]
        }
      }
    },
    "AnalyzerIntegrators": {
      "description": "Implements specialized AI-based code analysis tasks (security, lint, performance). Each method synchronously produces a Report.",
      "entities": [
        "ReviewEvent",
        "Rule",
        "Report"
      ],
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
          ],
          "trigger": "Invoked internally by RunTask to handle the 'security' sub-task.",
          "steps": [
            "Step1: Read code and relevant security rule data.",
            "Step2: Construct the AI model input for security analysis tasks.",
            "Step3: Call the integrated AI model to detect potential security issues.",
            "Step4: Generate a security-focused Report capturing identified issues and analysis time."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "SecurityAnalysisAIInvocation",
              "description": "Use AI-based logic to detect potential vulnerabilities in the code.",
              "source": "Plugin:AI/LLMInvocation"
            },
            {
              "capability": "ReportGeneration",
              "description": "Produce a specialized security report referencing discovered vulnerabilities.",
              "source": "SRS"
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
          ],
          "trigger": "Invoked internally by RunTask for the 'lint' sub-task.",
          "steps": [
            "Step1: Retrieve the code and relevant lint rule data.",
            "Step2: Construct AI input geared towards style and format checks.",
            "Step3: Invoke AI model to identify lint or style non-compliance.",
            "Step4: Generate a lint-oriented Report capturing identified style issues and analysis time."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "LintAnalysisAIInvocation",
              "description": "Use AI-based logic to check style and format issues in the code base.",
              "source": "Plugin:AI/LLMInvocation"
            },
            {
              "capability": "ReportGeneration",
              "description": "Produce a specialized lint report referencing code style or convention violations.",
              "source": "SRS"
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
          ],
          "trigger": "Invoked internally by RunTask for the 'performance' sub-task.",
          "steps": [
            "Step1: Retrieve the code and relevant performance rule data.",
            "Step2: Construct AI input focusing on performance patterns and potential optimizations.",
            "Step3: Invoke the AI model to analyze performance aspects.",
            "Step4: Generate a performance-focused Report highlighting bottlenecks and analysis time."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "PerformanceAnalysisAIInvocation",
              "description": "Utilize AI-based checks to locate performance hotspots in the code.",
              "source": "Plugin:AI/LLMInvocation"
            },
            {
              "capability": "ReportGeneration",
              "description": "Generate a specialized performance report capturing discovered issues and potential optimizations.",
              "source": "SRS"
            }
          ]
        }
      }
    },
    "ReportingFeedback": {
      "description": "Collects and stores code review results, generating comprehensive reports for developer consumption. Automates the posting of code review comments to GitLab merge requests and enables developer feedback.",
      "entities": [
        "Report"
      ],
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
          ],
          "trigger": "HTTP GET /api/reports/{event_id} with a valid event_id.",
          "steps": [
            "Step1: Query the system’s report records for the specified event_id.",
            "Step2: Return the matching report(s) to the caller."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "RetrieveReviewReports",
              "description": "Provide detailed analysis reports for a specified event, in compliance with FR-007.",
              "source": "SRS"
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
          ],
          "trigger": "HTTP POST /api/reports/{event_id}/gitlab-comment with comment_data.",
          "steps": [
            "Step1: Retrieve relevant report data for the specified event.",
            "Step2: Prepare the comment message referencing the review findings.",
            "Step3: Send an HTTP request to GitLab’s API to post the comment on the MR/PR page."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "ExternalRequestPreparation",
              "description": "Construct an outbound request to GitLab containing the relevant comment text.",
              "source": "Plugin:ExternalSystemInteraction"
            },
            {
              "capability": "MapResponseToSystem",
              "description": "Interpret GitLab’s response for logging or error-checking purposes, if any.",
              "source": "Plugin:ExternalSystemInteraction"
            },
            {
              "capability": "MRCommentAutomation",
              "description": "Automatically post code review commentary to GitLab, fulfilling FR-004.",
              "source": "SRS"
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
          ],
          "trigger": "HTTP POST /api/reports/{event_id}/feedback with feedback_data.",
          "steps": [
            "Step1: Retrieve the related report(s) for the specified event_id.",
            "Step2: Record or store the developer feedback for that report.",
            "Step3: Optionally update the report’s status or content with relevant feedback markers."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "StoreDeveloperFeedback",
              "description": "Record user feedback for a specific code review event to guide future improvements, referencing FR-012.",
              "source": "SRS"
            }
          ]
        }
      }
    },
    "AnalyticsStatistics": {
      "description": "Aggregates historical code review data for efficiency, quality trends, and frequent issues. Offers summary, heatmap, timeseries, and decision endpoints per the SRS.",
      "entities": [
        "Report"
      ],
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
          ],
          "trigger": "HTTP GET /api/analytics/summary is called to retrieve system-wide acceptance metrics.",
          "steps": [
            "Step1: Collect relevant historical report data from the data store.",
            "Step2: Calculate acceptance or improvement metrics by evaluating developer decisions on identified issues.",
            "Step3: Format and return the summary metrics to the caller."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "AggregateHistoricalData",
              "description": "Gather multiple reports’ data for acceptance rate computations.",
              "source": "Plugin:StatisticalAnalyticalOrTrendComputation"
            },
            {
              "capability": "AcceptanceRateComputation",
              "description": "Compute the ratio of accepted vs. rejected issues per FR-008.",
              "source": "SRS"
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
          ],
          "trigger": "HTTP GET /api/analytics/heatmap is called to visualize high-frequency problem areas.",
          "steps": [
            "Step1: Aggregate historical code review data across multiple events or time frames.",
            "Step2: Identify recurring or frequent issues using available metadata.",
            "Step3: Generate a heatmap structure highlighting those issues and return it."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "IssueFrequencyAnalysis",
              "description": "Use historical data to identify repeating problem patterns for heatmap generation.",
              "source": "Plugin:StatisticalAnalyticalOrTrendComputation"
            },
            {
              "capability": "HeatmapVisualRepresentation",
              "description": "Create data structures that can be rendered as a visual heatmap, satisfying FR-010.",
              "source": "SRS"
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
          ],
          "trigger": "HTTP GET /api/analytics/timeseries with optional parameters specifying a date range or scope.",
          "steps": [
            "Step1: Gather relevant historical reports over the specified time range.",
            "Step2: Compute time-series metrics such as number of issues identified per period or average review duration.",
            "Step3: Return the time-series data points."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "TrendComputations",
              "description": "Compute changes in code review metrics over time for FR-009 and FR-011.",
              "source": "Plugin:StatisticalAnalyticalOrTrendComputation"
            },
            {
              "capability": "TimeBasedAnalysis",
              "description": "Extract temporal patterns related to code review performance or issue detection rates.",
              "source": "SRS"
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
          ],
          "trigger": "HTTP POST /api/analytics/report/{report_id}/decision with a user’s acceptance or rejection input.",
          "steps": [
            "Step1: Retrieve the target report by its report_id.",
            "Step2: Update the report status or decision field with the provided acceptance or rejection data.",
            "Step3: Persist the updated report and finalize any derived analytics markers."
          ],
          "invoked_methods": [],
          "key_functional_points": [
            {
              "capability": "SetReportAcceptanceDecision",
              "description": "Record the developer’s explicit accept/reject decision for analytics correlation.",
              "source": "SRS"
            }
          ]
        }
      }
    }
  }
}