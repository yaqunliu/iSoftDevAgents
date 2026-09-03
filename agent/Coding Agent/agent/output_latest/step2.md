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
        "get_event": {
          "description": "Retrieve a specific event by event_id"
        },
        "get_pending_events": {
          "description": "List events currently in pending state"
        },
        "trigger_event": {
          "description": "Initiate or process the event"
        },
        "update_event_state": {
          "description": "Set an event’s state to a new value"
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
          "required": false,
          "mutable": true
        }
      },
      "relationships": {
      },
      "repository_operations": {
        "get_rules": {
          "description": "Retrieve the list of all rules"
        },
        "create_rule": {
          "description": "Create a new rule"
        },
        "update_rule": {
          "description": "Update an existing rule"
        },
        "delete_rule": {
          "description": "Delete a rule by rule_id"
        },
        "get_active_rules": {
          "description": "Retrieve rules that are currently enabled"
        }
      }
    },
    "Report": {
      "category": "intermediate",
      "module": "CodeAnalysisEngine",
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
        "reprot_content": {
          "type": "str",
          "required": false,
          "mutable": true
        },
        "processing_time": {
          "type": "float",
          "required": false,
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
        "get_report": {
          "description": "Retrieve a report for a given identifier"
        },
        "submit_report": {
          "description": "Store or update the analysis report"
        },
        "set_report_decision": {
          "description": "Apply a user decision to the generated report"
        }
      }
    }
  }
}