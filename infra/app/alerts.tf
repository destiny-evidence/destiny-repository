data "azurerm_log_analytics_workspace" "container_apps" {
  name                = module.container_app.container_app_env_name
  resource_group_name = azurerm_resource_group.this.name
}

resource "azurerm_logic_app_workflow" "slack_alerts" {
  count = local.env.alerts_enabled && var.alert_slack_webhook_url != "" ? 1 : 0

  name                = "${local.name}-slack-alerts"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  tags = local.minimum_resource_tags
}

# --- Metrics Alerts ---

resource "azurerm_logic_app_trigger_http_request" "slack_alerts" {
  count = local.env.alerts_enabled && var.alert_slack_webhook_url != "" ? 1 : 0

  name         = "azure-monitor-webhook"
  logic_app_id = azurerm_logic_app_workflow.slack_alerts[0].id

  # schema: https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alerts-common-schema
  schema = <<-SCHEMA
    {
      "type": "object",
      "properties": {
        "schemaId": { "type": "string" },
        "data": {
          "type": "object",
          "properties": {
            "essentials": {
              "type": "object",
              "properties": {
                "alertRule": { "type": "string" },
                "severity": { "type": "string" },
                "monitorCondition": { "type": "string" },
                "description": { "type": "string" },
                "firedDateTime": { "type": "string" },
                "configurationItems": { "type": "array" }
              }
            }
          }
        }
      }
    }
  SCHEMA
}

resource "azurerm_logic_app_action_http" "post_to_slack" {
  count = local.env.alerts_enabled && var.alert_slack_webhook_url != "" ? 1 : 0

  name         = "post-to-slack"
  logic_app_id = azurerm_logic_app_workflow.slack_alerts[0].id
  method       = "POST"
  uri          = var.alert_slack_webhook_url

  headers = {
    "Content-Type" = "application/json"
  }

  # body: https://api.slack.com/block-kit
  # expressions: https://learn.microsoft.com/en-us/azure/logic-apps/workflow-definition-language-functions-reference
  body = <<-BODY
    {
      "blocks": [
        {
          "type": "header",
          "text": {
            "type": "plain_text",
            "text": "@{if(equals(triggerBody()?['data']?['essentials']?['monitorCondition'], 'Resolved'), '✅ RESOLVED', if(equals(triggerBody()?['data']?['essentials']?['severity'], 'Sev0'), '🚨 CRITICAL', if(equals(triggerBody()?['data']?['essentials']?['severity'], 'Sev1'), '❌ ERROR', '⚠️ WARNING')))} @{triggerBody()?['data']?['essentials']?['alertRule']}",
            "emoji": true
          }
        },
        {
          "type": "section",
          "fields": [
            { "type": "mrkdwn", "text": "*Status:*\n@{triggerBody()?['data']?['essentials']?['monitorCondition']}" },
            { "type": "mrkdwn", "text": "*Severity:*\n@{triggerBody()?['data']?['essentials']?['severity']}" }
          ]
        },
        {
          "type": "section",
          "text": { "type": "mrkdwn", "text": "*Description:*\n@{triggerBody()?['data']?['essentials']?['description']}" }
        },
        {
          "type": "section",
          "text": { "type": "mrkdwn", "text": "*Resource:*\n@{first(triggerBody()?['data']?['essentials']?['configurationItems'])}" }
        },
        {
          "type": "context",
          "elements": [{ "type": "mrkdwn", "text": "Fired at @{triggerBody()?['data']?['essentials']?['firedDateTime']}" }]
        }
      ]
    }
  BODY
}

resource "azurerm_monitor_action_group" "alerts" {
  count = local.env.alerts_enabled ? 1 : 0

  name                = "${local.name}-alerts-ag"
  resource_group_name = azurerm_resource_group.this.name
  short_name          = "alerts"

  tags = local.minimum_resource_tags

  dynamic "email_receiver" {
    for_each = var.alert_email_recipients
    content {
      name                    = "email-${email_receiver.key}"
      email_address           = email_receiver.value
      use_common_alert_schema = true
    }
  }

  dynamic "logic_app_receiver" {
    for_each = var.alert_slack_webhook_url != "" ? [1] : []
    content {
      name                    = "slack-via-logic-app"
      resource_id             = azurerm_logic_app_workflow.slack_alerts[0].id
      callback_url            = azurerm_logic_app_trigger_http_request.slack_alerts[0].callback_url
      use_common_alert_schema = true
    }
  }
}

resource "azurerm_monitor_metric_alert" "db_storage_warning" {
  count = local.env.alerts_enabled ? 1 : 0

  name                = "${local.name}-db-storage-warning"
  resource_group_name = azurerm_resource_group.this.name
  scopes              = [azurerm_postgresql_flexible_server.this.id]
  description         = "Alert when PostgreSQL storage usage exceeds ${local.env.db_storage_warning_pct}%"
  severity            = 2 # warning
  frequency           = "PT5M"
  window_size         = "PT15M"

  tags = local.minimum_resource_tags

  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "storage_percent"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = local.env.db_storage_warning_pct
  }

  action {
    action_group_id = azurerm_monitor_action_group.alerts[0].id
  }
}

resource "azurerm_monitor_metric_alert" "db_storage_critical" {
  count = local.env.alerts_enabled ? 1 : 0

  name                = "${local.name}-db-storage-critical"
  resource_group_name = azurerm_resource_group.this.name
  scopes              = [azurerm_postgresql_flexible_server.this.id]
  description         = "CRITICAL: PostgreSQL storage usage exceeds ${local.env.db_storage_critical_pct}%"
  severity            = 0 # critical
  frequency           = "PT1M"
  window_size         = "PT5M"

  tags = local.minimum_resource_tags

  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "storage_percent"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = local.env.db_storage_critical_pct
  }

  action {
    action_group_id = azurerm_monitor_action_group.alerts[0].id
  }
}

resource "azurerm_monitor_metric_alert" "db_storage_rapid_increase" {
  count = local.env.alerts_enabled ? 1 : 0

  name                = "${local.name}-db-storage-rapid-increase"
  resource_group_name = azurerm_resource_group.this.name
  scopes              = [azurerm_postgresql_flexible_server.this.id]
  description         = "Alert when PostgreSQL storage usage increases rapidly (anomaly detection)"
  severity            = 2 # warning
  frequency           = "PT5M"
  window_size         = "PT1H"

  tags = local.minimum_resource_tags

  dynamic_criteria {
    metric_namespace  = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name       = "storage_percent"
    aggregation       = "Average"
    operator          = "GreaterThan"
    alert_sensitivity = "Medium"

    evaluation_total_count   = 4
    evaluation_failure_count = 4
  }

  action {
    action_group_id = azurerm_monitor_action_group.alerts[0].id
  }
}

resource "azurerm_monitor_metric_alert" "db_cpu_warning" {
  count = local.env.alerts_enabled ? 1 : 0

  name                = "${local.name}-db-cpu-warning"
  resource_group_name = azurerm_resource_group.this.name
  scopes              = [azurerm_postgresql_flexible_server.this.id]
  description         = "Alert when PostgreSQL CPU usage exceeds ${local.env.db_cpu_warning_pct}%"
  severity            = 2 # warning
  frequency           = "PT5M"
  window_size         = "PT15M"

  tags = local.minimum_resource_tags

  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "cpu_percent"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = local.env.db_cpu_warning_pct
  }

  action {
    action_group_id = azurerm_monitor_action_group.alerts[0].id
  }
}

resource "azurerm_monitor_metric_alert" "db_cpu_critical" {
  count = local.env.alerts_enabled ? 1 : 0

  name                = "${local.name}-db-cpu-critical"
  resource_group_name = azurerm_resource_group.this.name
  scopes              = [azurerm_postgresql_flexible_server.this.id]
  description         = "CRITICAL: PostgreSQL CPU usage exceeds ${local.env.db_cpu_critical_pct}%"
  severity            = 0 # critical
  frequency           = "PT1M"
  window_size         = "PT5M"

  tags = local.minimum_resource_tags

  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "cpu_percent"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = local.env.db_cpu_critical_pct
  }

  action {
    action_group_id = azurerm_monitor_action_group.alerts[0].id
  }
}

resource "azurerm_monitor_metric_alert" "db_memory_warning" {
  count = local.env.alerts_enabled ? 1 : 0

  name                = "${local.name}-db-memory-warning"
  resource_group_name = azurerm_resource_group.this.name
  scopes              = [azurerm_postgresql_flexible_server.this.id]
  description         = "Alert when PostgreSQL memory usage exceeds ${local.env.db_memory_warning_pct}%"
  severity            = 2 # warning
  frequency           = "PT5M"
  window_size         = "PT15M"

  tags = local.minimum_resource_tags

  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "memory_percent"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = local.env.db_memory_warning_pct
  }

  action {
    action_group_id = azurerm_monitor_action_group.alerts[0].id
  }
}

resource "azurerm_monitor_metric_alert" "db_memory_critical" {
  count = local.env.alerts_enabled ? 1 : 0

  name                = "${local.name}-db-memory-critical"
  resource_group_name = azurerm_resource_group.this.name
  scopes              = [azurerm_postgresql_flexible_server.this.id]
  description         = "CRITICAL: PostgreSQL memory usage exceeds ${local.env.db_memory_critical_pct}%"
  severity            = 0 # critical
  frequency           = "PT1M"
  window_size         = "PT5M"

  tags = local.minimum_resource_tags

  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = "memory_percent"
    aggregation      = "Average"
    operator         = "GreaterThan"
    threshold        = local.env.db_memory_critical_pct
  }

  action {
    action_group_id = azurerm_monitor_action_group.alerts[0].id
  }
}

resource "azurerm_monitor_metric_alert" "app_restart_count" {
  count = local.env.alerts_enabled ? 1 : 0

  name                = "${local.name}-app-restart-count"
  resource_group_name = azurerm_resource_group.this.name
  scopes              = [module.container_app.container_app_id]
  description         = "Alert when app container restart count exceeds 3"
  severity            = 1 # error
  frequency           = "PT1M"
  window_size         = "PT5M"

  tags = local.minimum_resource_tags

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "RestartCount"
    aggregation      = "Maximum"
    operator         = "GreaterThan"
    threshold        = 3
  }

  action {
    action_group_id = azurerm_monitor_action_group.alerts[0].id
  }
}

resource "azurerm_monitor_metric_alert" "tasks_restart_count" {
  count = local.env.alerts_enabled ? 1 : 0

  name                = "${local.name}-tasks-restart-count"
  resource_group_name = azurerm_resource_group.this.name
  scopes              = [module.container_app_tasks.container_app_id]
  description         = "Alert when tasks container restart count exceeds 3"
  severity            = 1 # error
  frequency           = "PT1M"
  window_size         = "PT5M"

  tags = local.minimum_resource_tags

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "RestartCount"
    aggregation      = "Maximum"
    operator         = "GreaterThan"
    threshold        = 3
  }

  action {
    action_group_id = azurerm_monitor_action_group.alerts[0].id
  }
}

resource "azurerm_monitor_metric_alert" "ui_restart_count" {
  count = local.env.alerts_enabled ? 1 : 0

  name                = "${local.name}-ui-restart-count"
  resource_group_name = azurerm_resource_group.this.name
  scopes              = [module.container_app_ui.container_app_id]
  description         = "Alert when UI container restart count exceeds 3"
  severity            = 1 # error
  frequency           = "PT1M"
  window_size         = "PT5M"

  tags = local.minimum_resource_tags

  criteria {
    metric_namespace = "Microsoft.App/containerApps"
    metric_name      = "RestartCount"
    aggregation      = "Maximum"
    operator         = "GreaterThan"
    threshold        = 3
  }

  action {
    action_group_id = azurerm_monitor_action_group.alerts[0].id
  }
}

# --- Log Analytics Search Alerts ---

resource "azurerm_logic_app_workflow" "slack_log_alerts" {
  count = local.env.alerts_enabled && var.alert_slack_webhook_url != "" ? 1 : 0

  name                = "${local.name}-slack-log-alerts"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  tags = local.minimum_resource_tags
}

resource "azurerm_logic_app_trigger_http_request" "slack_log_alerts" {
  count = local.env.alerts_enabled && var.alert_slack_webhook_url != "" ? 1 : 0

  name         = "azure-monitor-webhook"
  logic_app_id = azurerm_logic_app_workflow.slack_log_alerts[0].id

  # schema: https://learn.microsoft.com/en-us/azure/azure-monitor/alerts/alerts-common-schema
  schema = <<-SCHEMA
    {
      "type": "object",
      "properties": {
        "schemaId": { "type": "string" },
        "data": {
          "type": "object",
          "properties": {
            "essentials": {
              "type": "object",
              "properties": {
                "alertRule": { "type": "string" },
                "severity": { "type": "string" },
                "monitorCondition": { "type": "string" },
                "description": { "type": "string" },
                "firedDateTime": { "type": "string" }
              }
            },
            "alertContext": { "type": "object" }
          }
        }
      }
    }
  SCHEMA
}

resource "azurerm_logic_app_action_http" "post_log_alert_to_slack" {
  count = local.env.alerts_enabled && var.alert_slack_webhook_url != "" ? 1 : 0

  name         = "post-log-alert-to-slack"
  logic_app_id = azurerm_logic_app_workflow.slack_log_alerts[0].id
  method       = "POST"
  uri          = var.alert_slack_webhook_url

  headers = {
    "Content-Type" = "application/json"
  }

  # body: https://api.slack.com/block-kit
  # expressions: https://learn.microsoft.com/en-us/azure/logic-apps/workflow-definition-language-functions-reference
  body = <<-BODY
    {
      "blocks": [
        {
          "type": "header",
          "text": {
            "type": "plain_text",
            "text": "@{if(equals(triggerBody()?['data']?['essentials']?['monitorCondition'], 'Resolved'), '✅ RESOLVED', '❌ FAILURE')} @{first(triggerBody()?['data']?['alertContext']?['condition']?['allOf'][0]?['dimensions'])?['value']}",
            "emoji": true
          }
        },
        {
          "type": "section",
          "fields": [
            { "type": "mrkdwn", "text": "*Status:*\n@{triggerBody()?['data']?['essentials']?['monitorCondition']}" },
            { "type": "mrkdwn", "text": "*Alert Events:*\n@{if(equals(triggerBody()?['data']?['essentials']?['monitorCondition'], 'Resolved'), '0', string(triggerBody()?['data']?['alertContext']?['condition']?['allOf'][0]?['metricValue']))}" }
          ]
        },
        {
          "type": "section",
          "text": { "type": "mrkdwn", "text": "*Description:*\n@{triggerBody()?['data']?['essentials']?['description']}" }
        },
        {
          "type": "section",
          "text": { "type": "mrkdwn", "text": "<@{triggerBody()?['data']?['alertContext']?['condition']?['allOf'][0]?['linkToFilteredSearchResultsUI']}|🔍 View matching logs>" }
        },
        {
          "type": "context",
          "elements": [{ "type": "mrkdwn", "text": "@{triggerBody()?['data']?['essentials']?['alertRule']} · fired at @{triggerBody()?['data']?['essentials']?['firedDateTime']}" }]
        }
      ]
    }
  BODY
}

resource "azurerm_monitor_action_group" "log_alerts" {
  count = local.env.alerts_enabled ? 1 : 0

  name                = "${local.name}-log-alerts-ag"
  resource_group_name = azurerm_resource_group.this.name
  short_name          = "logalerts"

  tags = local.minimum_resource_tags

  dynamic "email_receiver" {
    for_each = var.alert_email_recipients
    content {
      name                    = "email-${email_receiver.key}"
      email_address           = email_receiver.value
      use_common_alert_schema = true
    }
  }

  dynamic "logic_app_receiver" {
    for_each = var.alert_slack_webhook_url != "" ? [1] : []
    content {
      name                    = "slack-via-logic-app"
      resource_id             = azurerm_logic_app_workflow.slack_log_alerts[0].id
      callback_url            = azurerm_logic_app_trigger_http_request.slack_log_alerts[0].callback_url
      use_common_alert_schema = true
    }
  }
}

# "FailedMount" and "FailedToRetrieveImagePullSecret" are purposefully excluded
# from the alert as these do not appear to stop the container app job running successfully
# and would be unactionable alert noise.
resource "azurerm_monitor_scheduled_query_rules_alert_v2" "job_failure_events" {
  count = local.env.alerts_enabled ? 1 : 0

  name                = "${local.name}-job-failure-events"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  scopes              = [data.azurerm_log_analytics_workspace.container_apps.id]
  description         = "A container app job in ${var.environment} has failed."
  severity            = 1 # error

  evaluation_frequency    = "PT1M"
  window_duration         = "PT5M"
  auto_mitigation_enabled = true

  tags = local.minimum_resource_tags

  criteria {
    query = <<-KQL
      ContainerAppSystemLogs_CL
      | where Type_s != "Normal"
        and JobName_s != ""
        and Reason_s !in ("FailedMount", "FailedToRetrieveImagePullSecret")
      | project TimeGenerated, JobName_s, Reason_s, Log_s
    KQL

    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 0

    # Splitting on the job name gives each job its own alert instance, puts the name
    # in the payload.
    dimension {
      name     = "JobName_s"
      operator = "Include"
      values   = ["*"]
    }

    failing_periods {
      number_of_evaluation_periods             = 1
      minimum_failing_periods_to_trigger_alert = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.log_alerts[0].id]
  }
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "job_error_logs" {
  count = local.env.alerts_enabled ? 1 : 0

  name                = "${local.name}-job-error-logs"
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  scopes              = [data.azurerm_log_analytics_workspace.container_apps.id]
  description         = "A container app job in ${var.environment} has logged an error."
  severity            = 1 # error

  evaluation_frequency    = "PT1M"
  window_duration         = "PT5M"
  auto_mitigation_enabled = true

  tags = local.minimum_resource_tags

  criteria {
    # Returning the lines within 10s of a failure
    query = <<-KQL
      let failures = ContainerAppConsoleLogs_CL
        | where ContainerJobName_s != ""
        | extend Level = coalesce(extract(@"level=(\w+)", 1, Log_s), extract(@"\[(\w+)\s*\]", 1, Log_s))
        | where Level in ("error", "critical")
          or Log_s has "Traceback (most recent call last)"
        | summarize FirstFailure = min(TimeGenerated), LastFailure = max(TimeGenerated) by ContainerGroupName_s;
      ContainerAppConsoleLogs_CL
      | join kind=inner failures on ContainerGroupName_s
      | where TimeGenerated between (FirstFailure - 10s .. LastFailure + 10s)
      | project TimeGenerated, ContainerJobName_s, ContainerGroupName_s, Log_s
    KQL

    time_aggregation_method = "Count"
    operator                = "GreaterThan"
    threshold               = 0

    # Splitting on the job name gives each job its own alert instance, puts the name
    # in the payload.
    dimension {
      name     = "ContainerJobName_s"
      operator = "Include"
      values   = ["*"]
    }

    failing_periods {
      number_of_evaluation_periods             = 1
      minimum_failing_periods_to_trigger_alert = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.log_alerts[0].id]
  }
}
