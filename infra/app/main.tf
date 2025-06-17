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

resource "azurerm_user_assigned_identity" "container_apps_tasks_identity" {
  name                = "${local.name}-tasks"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
}


data "azuread_group" "db_crud_group" {
  object_id = var.db_crud_group_id
}

data "azuread_group" "db_admin_group" {
  object_id = var.db_admin_group_id
}

resource "azuread_group_member" "container_app_to_crud" {
  group_object_id  = var.db_crud_group_id
  member_object_id = azurerm_user_assigned_identity.container_apps_identity.principal_id
}

resource "azuread_group_member" "container_app_tasks_to_crud" {
  group_object_id  = var.db_crud_group_id
  member_object_id = azurerm_user_assigned_identity.container_apps_tasks_identity.principal_id
}


locals {
  env_vars = [
    {
      name  = "APP_NAME"
      value = var.app_name
    },
    {
      name  = "AZURE_APPLICATION_ID"
      value = azuread_application_registration.destiny_repository.client_id
    },
    {
      name  = "AZURE_TENANT_ID"
      value = var.azure_tenant_id
    },
    {
      name = "DB_CONFIG",
      value = jsonencode({
        DB_FQDN = azurerm_postgresql_flexible_server.this.fqdn
        DB_NAME = azurerm_postgresql_flexible_server_database.this.name
        DB_USER = data.azuread_group.db_crud_group.display_name
      })
    },
    {
      name  = "ENV"
      value = var.environment
    },
    {
      name  = "MESSAGE_BROKER_NAMESPACE"
      value = "${azurerm_servicebus_namespace.this.name}.servicebus.windows.net"
    },
    {
      name  = "MESSAGE_BROKER_QUEUE_NAME"
      value = azurerm_servicebus_queue.taskiq.name
    },
    {
      name = "AZURE_BLOB_CONFIG"
      value = jsonencode({
        storage_account_name = azurerm_storage_account.this.name
        container            = azurerm_storage_container.operations.name
      })
    }
  ]

  secrets = [
    {
      name = "db-config-init-container",
      value = jsonencode({
        DB_FQDN = azurerm_postgresql_flexible_server.this.fqdn
        DB_NAME = azurerm_postgresql_flexible_server_database.this.name
        DB_USER = var.admin_login
        DB_PASS = var.admin_password
      })
    },
    {
      name  = "servicebus-connection-string"
      value = azurerm_servicebus_namespace.this.default_primary_connection_string
    },
  ]
}

module "container_app" {
  source                          = "app.terraform.io/destiny-evidence/container-app/azure"
  version                         = "1.5.0"
  app_name                        = var.app_name
  cpu                             = var.container_app_cpu
  environment                     = var.environment
  container_registry_id           = data.azurerm_container_registry.this.id
  container_registry_login_server = data.azurerm_container_registry.this.login_server
  infrastructure_subnet_id        = azurerm_subnet.app.id
  memory                          = var.container_app_memory
  resource_group_name             = azurerm_resource_group.this.name
  region                          = azurerm_resource_group.this.location
  max_replicas                    = var.app_max_replicas
  tags                            = local.minimum_resource_tags

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
    image   = "${data.azurerm_container_registry.this.login_server}/destiny-repository:${var.environment}"
    command = ["alembic", "upgrade", "head"]
    cpu     = 0.5
    memory  = "1Gi"

    # Init containers don't support managed identities so this is our last bastion
    # of passworded auth.
    # https://github.com/microsoft/azure-container-apps/issues/807
    env = concat(local.env_vars, [
      {
        name        = "DB_CONFIG",
        secret_name = "db-config-init-container"
      }
    ])
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

module "container_app_tasks" {
  source                          = "app.terraform.io/destiny-evidence/container-app/azure"
  version                         = "1.5.0"
  app_name                        = "${var.app_name}-task"
  cpu                             = var.container_app_tasks_cpu
  environment                     = var.environment
  container_registry_id           = data.azurerm_container_registry.this.id
  container_registry_login_server = data.azurerm_container_registry.this.login_server
  infrastructure_subnet_id        = azurerm_subnet.tasks.id
  memory                          = var.container_app_tasks_memory
  resource_group_name             = azurerm_resource_group.this.name
  region                          = azurerm_resource_group.this.location
  max_replicas                    = var.tasks_max_replicas
  tags                            = local.minimum_resource_tags

  identity = {
    id           = azurerm_user_assigned_identity.container_apps_tasks_identity.id
    principal_id = azurerm_user_assigned_identity.container_apps_tasks_identity.principal_id
    client_id    = azurerm_user_assigned_identity.container_apps_tasks_identity.client_id
  }

  env_vars = concat(local.env_vars, [
    {
      name  = "APP_NAME"
      value = "${var.app_name}-task"
    },
  ])
  secrets = local.secrets

  command = ["taskiq", "worker", "app.tasks:broker", "--fs-discover"]

  # Unfortunately the Azure terraform provider doesn't support setting up managed identity auth for scaling rules.
  custom_scale_rules = [
    {
      name             = "queue-length-scale-rule"
      custom_rule_type = "azure-servicebus"
      metadata = {
        namespace   = azurerm_servicebus_namespace.this.name
        queueName   = azurerm_servicebus_queue.taskiq.name
        queueLength = var.queue_length_scaling_threshold
      }
      authentication = {
        secret_name       = "servicebus-connection-string"
        trigger_parameter = "connection"
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
    password_auth_enabled         = true # required for init container, see https://covidence.atlassian.net/wiki/spaces/Platforms/pages/624033793/DESTINY+DB+Authentication
    active_directory_auth_enabled = true
    tenant_id                     = var.azure_tenant_id
  }

  depends_on = [azurerm_private_dns_zone_virtual_network_link.db]
  tags       = local.minimum_resource_tags
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

resource "azurerm_servicebus_namespace" "this" {
  name                = local.name
  resource_group_name = azurerm_resource_group.this.name
  location            = azurerm_resource_group.this.location
  sku                 = "Standard"

  tags = local.minimum_resource_tags
}

resource "azurerm_servicebus_queue" "taskiq" {
  name         = "taskiq"
  namespace_id = azurerm_servicebus_namespace.this.id

  partitioning_enabled = true
}

resource "azurerm_storage_account" "this" {
  # Storage account name ust be less than 24 characters, only lowercase letters and numbers,
  # and globally unique. This is the best we can do.
  name                     = "${replace(var.app_name, "-", "")}${substr(var.environment, 0, 4)}sa"
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  tags                     = local.minimum_resource_tags

  # Avoid accidental blob storage deletion
  lifecycle {
    prevent_destroy = true
  }
}


resource "azurerm_storage_container" "operations" {
  # This is a container designed for storing operational repository files such as
  # batch enhancement results and reference data for robots. These are transient.
  # We should segregate this from permanent data (such as full texts) at the container
  # level to easily apply different storage management policies.
  name                  = "${local.name}-ops"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

resource "azurerm_storage_management_policy" "operations" {
  storage_account_id = azurerm_storage_account.this.id

  rule {
    name    = "delete-old-${azurerm_storage_container.operations.name}-blobs"
    enabled = false # Disabled for now, enable once comfortable
    filters {
      blob_types   = ["blockBlob"]
      prefix_match = [azurerm_storage_container.operations.name]
    }
    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = 30
      }
      snapshot {
        delete_after_days_since_creation_greater_than = 30
      }
      version {
        delete_after_days_since_creation = 30
      }
    }
  }
}

resource "azurerm_role_assignment" "blob_storage_rw" {
  # TODO: granularise permissions per container
  for_each = {
    app        = azurerm_user_assigned_identity.container_apps_identity.principal_id
    tasks      = azurerm_user_assigned_identity.container_apps_tasks_identity.principal_id
    developers = var.developers_group_id
  }
  scope                = azurerm_storage_account.this.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = each.value
}
