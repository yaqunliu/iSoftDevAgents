{
  "external_api_analysis": {
    "modules": {
      "WebhookEventIngestion": {
        "methods": {
          "handleGitLabWebhook": {
            "method_name": "HandleGitLabWebhook",
            "external_api_calls": []
          },
          "handleManualTrigger": {
            "method_name": "HandleManualTrigger",
            "external_api_calls": []
          }
        }
      },
      "ReviewEventTracking": {
        "methods": {
          "get_pending_events": {
            "method_name": "GetPendingEvents",
            "external_api_calls": []
          },
          "get_event": {
            "method_name": "GetEvent",
            "external_api_calls": []
          },
          "trigger_event": {
            "method_name": "TriggerEvent",
            "external_api_calls": []
          },
          "update_event_state": {
            "method_name": "UpdateEventState",
            "external_api_calls": []
          }
        }
      },
      "RuleManagement": {
        "methods": {
          "get_rules": {
            "method_name": "GetRules",
            "external_api_calls": []
          },
          "create_rule": {
            "method_name": "CreateRule",
            "external_api_calls": []
          },
          "update_rule": {
            "method_name": "UpdateRule",
            "external_api_calls": []
          },
          "delete_rule": {
            "method_name": "DeleteRule",
            "external_api_calls": []
          },
          "get_active_rules": {
            "method_name": "GetActiveRules",
            "external_api_calls": []
          }
        }
      },
      "CodeAnalysisEngine": {
        "methods": {
          "run_pipeline": {
            "method_name": "RunPipeline",
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
          "run_task": {
            "method_name": "RunTask",
            "external_api_calls": []
          }
        }
      },
      "AnalyzerIntegrators": {
        "methods": {
          "analyze_security": {
            "method_name": "AnalyzeSecurity",
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
          "analyze_lint": {
            "method_name": "AnalyzeLint",
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
          "analyze_performance": {
            "method_name": "AnalyzePerformance",
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
        "methods": {
          "get_report": {
            "method_name": "GetReport",
            "external_api_calls": []
          },
          "post_gitlab_comment": {
            "method_name": "PostGitlabComment",
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
          "post_feedback": {
            "method_name": "PostFeedback",
            "external_api_calls": []
          }
        }
      },
      "AnalyticsStatistics": {
        "methods": {
          "get_summary": {
            "method_name": "GetSummary",
            "external_api_calls": []
          },
          "get_heatmap": {
            "method_name": "GetHeatmap",
            "external_api_calls": []
          },
          "get_timeseries": {
            "method_name": "GetTimeseries",
            "external_api_calls": []
          },
          "set_report_decision": {
            "method_name": "SetReportDecision",
            "external_api_calls": []
          }
        }
      }
    }
  }
}