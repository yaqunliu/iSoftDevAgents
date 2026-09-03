{
  "entities": {
    "ReviewEvent": {
      "category": "core",
      "module": "ReviewEventTracking",
      "primary_key": {
        "fields": ["event_id"]
      },
      "fields": {
        "event_id": {
          "type": "str",
          "required": true,
          "mutable": false
        },
        "state": {
          "type": "enum",
          "enum_values": ["pending", "running", "completed", "failed"],
          "required": true,
          "mutable": true
        },
        "source": {
          "type": "str",
          "required": true,
          "mutable": true
        },
        "code": {
          "type": "str",
          "required": true,
          "mutable": true
        }
      },
      "relationships": {
        "Report": {
          "type": "1:N",
          "direction": "parent→child"
        }
      },
      "repository_operations": {
        "get_by_id": {
          "description": "Retrieves a single review event by event_id"
        },
        "list_pending": {
          "description": "Lists all events in pending state"
        },
        "trigger_event": {
          "description": "Initiates review event analysis pipeline"
        },
        "update_state": {
          "description": "Updates the state of a review event"
        }
      }
    },
    "Rule": {
      "category": "core",
      "module": "RuleManagement",
      "primary_key": {
        "fields": ["rule_id"]
      },
      "fields": {
        "rule_id": {
          "type": "str",
          "required": true,
          "mutable": false
        },
        "enabled": {
          "type": "bool",
          "required": true,
          "mutable": true
        },
        "rule_data": {
          "type": "dict",
          "required": true,
          "mutable": true
        }
      },
      "relationships": {
      },
      "repository_operations": {
        "get_rules": {
          "description": "Retrieves all defined rules"
        },
        "create_rule": {
          "description": "Creates a new rule with provided data"
        },
        "update_rule": {
          "description": "Updates an existing rule data"
        },
        "delete_rule": {
          "description": "Deletes a rule by rule_id"
        },
        "get_active_rules": {
          "description": "Retrieves rules that are currently enabled"
        }
      }
    },
    "Report": {
      "category": "intermediate",
      "module": "ReportingFeedback",
      "primary_key": {
        "fields": ["report_id"]
      },
      "fields": {
        "report_id": {
          "type": "str",
          "required": true,
          "mutable": false
        },
        "event_id": {
          "type": "str",
          "required": true,
          "mutable": false
        },
        "type": {
          "type": "enum",
          "enum_values": ["security", "lint", "performance"],
          "required": true,
          "mutable": false
        },
        "report_content": {
          "type": "str",
          "required": true,
          "mutable": true
        },
        "processing_time": {
          "type": "float",
          "required": true,
          "mutable": true
        },
        "status": {
          "type": "enum",
          "enum_values": ["pending", "running", "completed", "failed"],
          "required": true,
          "mutable": true
        }
      },
      "relationships": {
        "ReviewEvent": {
          "type": "1:N",
          "direction": "child→parent"
        }
      },
      "repository_operations": {
        "get_by_event_id": {
          "description": "Retrieves a report or set of reports for the given event"
        },
        "persist_report": {
          "description": "Stores or updates a report record"
        },
        "post_gitlab_comment": {
          "description": "Submits a comment to GitLab referencing this report"
        },
        "post_feedback": {
          "description": "Submits developer feedback for this report"
        }
      }
    }
  }
}