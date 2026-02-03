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

  dynamic "webhook_receiver" {
    for_each = var.alert_slack_webhook_url != "" ? [1] : []
    content {
      name                    = "slack"
      service_uri             = var.alert_slack_webhook_url
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
