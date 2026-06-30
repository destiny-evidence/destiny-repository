resource "azurerm_logic_app_workflow" "slack_alerts" {
  count = local.env.alerts_enabled && var.alert_slack_webhook_url != "" ? 1 : 0

  name                = "${local.name}-slack-alerts"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  tags = local.minimum_resource_tags
}

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
            "text": "@{if(equals(triggerBody()?['data']?['essentials']?['severity'], 'Sev0'), '🚨 CRITICAL', if(equals(triggerBody()?['data']?['essentials']?['severity'], 'Sev1'), '❌ ERROR', '⚠️ WARNING'))} @{triggerBody()?['data']?['essentials']?['alertRule']}",
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
