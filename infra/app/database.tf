locals {
  database_migrator_name = "db-migrator-${var.environment}"
}

data "azuread_group" "db_crud_group" {
  object_id = var.db_crud_group_id
}

data "azuread_group" "db_admin_group" {
  object_id = var.db_admin_group_id
}

resource "azurerm_postgresql_flexible_server_database" "this" {
  name      = "${local.name}-db"
  server_id = azurerm_postgresql_flexible_server.this.id
  collation = "en_US.utf8"
  charset   = "UTF8"

  # Avoid accidental database deletion
  lifecycle {
    prevent_destroy = true
  }
}

resource "azurerm_postgresql_flexible_server" "this" {
  name                          = "${local.name}-psqlflexibleserver"
  resource_group_name           = azurerm_resource_group.this.name
  location                      = azurerm_resource_group.this.location
  version                       = "16"
  delegated_subnet_id           = azurerm_subnet.db.id
  private_dns_zone_id           = azurerm_private_dns_zone.db.id
  public_network_access_enabled = false
  administrator_login           = var.admin_login
  administrator_password        = var.admin_password
  zone                          = "1"
  backup_retention_days         = local.env.db_backup_days

  dynamic "high_availability" {
    for_each = local.env.db_ha_enabled ? [1] : []
    content {
      mode = "ZoneRedundant"
    }
  }

  storage_mb   = local.env.db_storage_mb
  storage_tier = local.env.db_storage_tier

  sku_name = "GP_Standard_D2ds_v4"

  authentication {
    password_auth_enabled         = true # required for init container, see https://covidence.atlassian.net/wiki/spaces/Platforms/pages/624033793/DESTINY+DB+Authentication
    active_directory_auth_enabled = true
    tenant_id                     = var.azure_tenant_id
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.db]
  tags       = local.minimum_resource_tags

  # avoid migrating back to the primary availability zone after failover
  lifecycle {
    ignore_changes = [
      zone,
      high_availability[0].standby_availability_zone
    ]
  }
}

resource "azurerm_user_assigned_identity" "pgadmin" {
  location            = azurerm_resource_group.this.location
  name                = data.azuread_group.db_admin_group.display_name
  resource_group_name = azurerm_resource_group.this.name
  tags                = local.minimum_resource_tags
}

resource "azurerm_postgresql_flexible_server_active_directory_administrator" "admin" {
  server_name         = azurerm_postgresql_flexible_server.this.name
  resource_group_name = azurerm_resource_group.this.name
  tenant_id           = var.azure_tenant_id
  object_id           = var.db_admin_group_id
  principal_name      = data.azuread_group.db_admin_group.display_name
  principal_type      = "Group"
}

resource "azurerm_user_assigned_identity" "database_migrator" {
  name                = "${var.app_name}-${local.database_migrator_name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
}

resource "azurerm_role_assignment" "db_migrator_acr_access" {
  principal_id         = azurerm_user_assigned_identity.database_migrator.principal_id
  scope                = data.azurerm_container_registry.this.id
  role_definition_name = "AcrPull"

  # terraform seems unable to replace the role assignment, so we need to ignore changes
  lifecycle {
    ignore_changes = [principal_id, scope]
  }
}

resource "azurerm_container_app_job" "database_migrator" {
  name                         = local.database_migrator_name
  location                     = azurerm_resource_group.this.location
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = module.container_app.container_app_env_id

  replica_timeout_in_seconds = var.database_migrator_timeout

  # If the replica fails, do not retry
  replica_retry_limit = 0

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  registry {
    identity = azurerm_user_assigned_identity.database_migrator.id
    server   = data.azurerm_container_registry.this.login_server
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.database_migrator.id]
  }

  secret {
    name = "otel-config"
    value = jsonencode({
      trace_endpoint = var.honeycombio_trace_endpoint
      meter_endpoint = var.honeycombio_meter_endpoint
      log_endpoint   = var.honeycombio_log_endpoint
      api_key        = honeycombio_api_key.this.key
    })
  }

  secret {
    name = "db-config"
    value = jsonencode({
      DB_FQDN = azurerm_postgresql_flexible_server.this.fqdn
      DB_NAME = azurerm_postgresql_flexible_server_database.this.name
      DB_USER = var.admin_login
      DB_PASS = var.admin_password
    })
  }

  template {
    container {
      image   = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
      name    = "${local.database_migrator_name}0"
      command = ["alembic", "upgrade", "head"]

      cpu    = 0.5
      memory = "1Gi"

      env {
        name  = "APP_NAME"
        value = local.database_migrator_name
      }

      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.database_migrator.client_id
      }

      env {
        name        = "OTEL_CONFIG"
        secret_name = "otel-config"
      }

      env {
        name        = "DB_CONFIG"
        secret_name = "db-config"
      }

      env {
        name  = "ENV"
        value = var.environment
      }

      env {
        name  = "OTEL_ENABLED"
        value = var.telemetry_enabled
      }
    }
  }

  # Allow us to update the image via github actions
  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}
