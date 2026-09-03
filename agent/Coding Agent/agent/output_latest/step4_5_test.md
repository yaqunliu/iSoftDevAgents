{
  "external_api_analysis": {
    "modules": {
      "AnalyzerIntegrators": {
        "methods": {
          "analyze_security": {
            "method_name": "AnalyzeSecurity",
            "external_api_calls": [
              {
                "api_name": "AI 模型（GPT、Claude、Gemini）",
                "operation": "执行自动化代码分析",
                "srs_requirement": "FR-003",
                "purpose": "Perform security vulnerability analysis on code",
                "data_direction": "bidirectional"
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
                "purpose": "Detect code style and normative compliance issues",
                "data_direction": "bidirectional"
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
                "purpose": "Provide performance improvement suggestions",
                "data_direction": "bidirectional"
              }
            ]
          }
        }
      },
      "ReportingFeedback": {
        "methods": {
          "post_gitlab_comment": {
            "method_name": "PostGitlabComment",
            "external_api_calls": [
              {
                "api_name": "GitLab",
                "operation": "提交审查评论",
                "srs_requirement": "FR-004",
                "purpose": "Automate posting code review comments to GitLab MR/PR",
                "data_direction": "send"
              }
            ]
          }
        }
      }
    }
  }
}