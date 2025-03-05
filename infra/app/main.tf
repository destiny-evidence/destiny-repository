# Azure container registry will be defined in shared infrastructure repository
data "azurerm_container_registry" "registry" {
  name                = var.container_registry_name
  resource_group_name = var.container_registry_resource_group
}

resource "azurerm_resource_group" "this" {
  name     = local.name
  location = var.region
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
      name  = "ENVIRONMENT"
      value = var.environment
    }
  ]
}

module "container_app" {
  source                          = "app.terraform.io/future-evidence-foundation/container-app/azure"
  version                         = "1.0.0"
  app_name                        = var.app_name
  environment                     = var.environment
  container_registry_id           = data.azurerm_container_registry.registry.id
  container_registry_login_server = data.azurerm_container_registry.registry.login_server
  resource_group_name             = azurerm_resource_group.this.name
  region                          = azurerm_resource_group.this.location
  max_replicas                    = var.app_max_replicas

  identity = {
    id           = azurerm_user_assigned_identity.container_apps_identity.id
    principal_id = azurerm_user_assigned_identity.container_apps_identity.principal_id
    client_id    = azurerm_user_assigned_identity.container_apps_identity.client_id
  }

  env_vars = local.env_vars

  # NOTE: ingress changes will be ignored to avoid messing up manual custom domain config. See https://github.com/hashicorp/terraform-provider-azurerm/issues/21866#issuecomment-1755381572.
  ingress = {
    external_enabled           = true
    allow_insecure_connections = false
    target_port                = 80
    transport                  = "auto"
    traffic_weight = {
      latest_revision = true
      percentage      = 100
    }
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
