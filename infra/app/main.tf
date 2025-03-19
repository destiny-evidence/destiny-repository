# Azure container registry will be defined in shared infrastructure repository
data "azurerm_container_registry" "this" {
  name                = var.container_registry_name
  resource_group_name = var.container_registry_resource_group
}

resource "azurerm_resource_group" "this" {
  name     = "rg-${local.name}"
  location = var.region
  tags     = merge({ "Budget Code" = var.budget_code }, local.minimum_resource_tags)
}

resource "azurerm_user_assigned_identity" "container_apps_identity" {
  name                = local.name
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
}

locals {
  env_vars = [
    {
      name  = "APP_NAME"
      value = var.app_name
    },
    {
      name  = "AZURE_APPLICATION_ID"
      value = var.azure_application_id
    },
    {
      name  = "AZURE_TENANT_ID"
      value = var.azure_tenant_id
    },
    {
      name        = "DB_URL"
      secret_name = "db-url"
    },
    {
      name  = "ENVIRONMENT"
      value = var.environment
    }
  ]

  secrets = [
    {
      name  = "db-url"
      value = "postgresql+asyncpg://${var.admin_login}:${var.admin_password}@${azurerm_postgresql_flexible_server.this.fqdn}:5432/${azurerm_postgresql_flexible_server_database.this.name}"
    }
  ]
}

module "container_app" {
  source                          = "app.terraform.io/future-evidence-foundation/container-app/azure"
  version                         = "1.2.0"
  app_name                        = var.app_name
  environment                     = var.environment
  container_registry_id           = data.azurerm_container_registry.this.id
  container_registry_login_server = data.azurerm_container_registry.this.login_server
  infrastructure_subnet_id        = azurerm_subnet.app.id
  resource_group_name             = azurerm_resource_group.this.name
  region                          = azurerm_resource_group.this.location
  max_replicas                    = var.app_max_replicas

  identity = {
    id           = azurerm_user_assigned_identity.container_apps_identity.id
    principal_id = azurerm_user_assigned_identity.container_apps_identity.principal_id
    client_id    = azurerm_user_assigned_identity.container_apps_identity.client_id
  }

  env_vars = local.env_vars
  secrets  = local.secrets

  # NOTE: ingress changes will be ignored to avoid messing up manual custom domain config. See https://github.com/hashicorp/terraform-provider-azurerm/issues/21866#issuecomment-1755381572.
  ingress = {
    external_enabled           = true
    allow_insecure_connections = false
    target_port                = 8000
    transport                  = "auto"
    traffic_weight = {
      latest_revision = true
      percentage      = 100
    }
  }

  init_container = {
    name    = "${local.name}-database-init"
    image   = "futureevidence.azurecr.io/destiny-repository:${var.environment}"
    command = ["/venv/bin/alembic", "upgrade", "head"]
    cpu     = 0.5
    memory  = "1Gi"
    env = [
      {
        name  = "AZURE_APPLICATION_ID"
        value = var.azure_application_id
      },
      {
        name  = "AZURE_TENANT_ID"
        value = var.azure_tenant_id
      },
      {
        name        = "DB_URL"
        secret_name = "db-url"
      }
    ]
  }

  custom_scale_rules = [
    {
      name             = "cpu-scale-rule"
      custom_rule_type = "cpu"
      metadata = {
        type  = "Utilization"
        value = var.cpu_scaling_threshold
      }
    }
  ]
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

  storage_mb   = 32768
  storage_tier = "P4"

  sku_name = "GP_Standard_D2ds_v4"

  authentication {
    # We'll want to update this to use Entra ID & managed identities for access
    password_auth_enabled = true
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.db]
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
