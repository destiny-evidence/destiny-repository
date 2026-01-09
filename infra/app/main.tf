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

resource "azurerm_user_assigned_identity" "container_apps_ui_identity" {
  name                = "${local.name}-ui"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
}

resource "azurerm_user_assigned_identity" "es_index_migrator" {
  name                = local.es_index_migrator_name
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
  # When external directory is enabled, use the external directory app and tenant
  # Otherwise, use the application tenant
  auth_application_id = var.external_directory_enabled ? azuread_application.external_directory_destiny_repository.client_id : azuread_application.destiny_repository.client_id
  auth_login_url      = var.external_directory_enabled ? var.azure_login_url : "https://login.microsoftonline.com/${var.azure_tenant_id}"

  env_vars = [
    {
      name  = "APP_NAME"
      value = var.app_name
    },
    {
      name  = "AZURE_APPLICATION_ID"
      value = local.auth_application_id
    },
    {
      name  = "AZURE_LOGIN_URL"
      value = local.auth_login_url
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
    },
    {
      name        = "ES_CONFIG"
      secret_name = "es-config"
    },
    {
      name        = "OTEL_CONFIG"
      secret_name = "otel-config"
    },
    {
      name  = "OTEL_ENABLED",
      value = var.telemetry_enabled
    },
    {
      name  = "FEATURE_FLAGS"
      value = jsonencode(var.feature_flags)
    },
    {
      name  = "DEFAULT_UPLOAD_FILE_CHUNK_SIZE",
      value = tostring(var.default_upload_file_chunk_size)
    },
    {
      name  = "MAX_REFERENCE_LOOKUP_QUERY_LENGTH",
      value = var.max_reference_lookup_query_length
    },
    {
      name  = "MESSAGE_LOCK_RENEWAL_DURATION",
      value = var.message_lock_renewal_duration
    },
    {
      name  = "TRUSTED_UNIQUE_IDENTIFIER_TYPES",
      value = jsonencode(var.trusted_unique_identifier_types)
    },
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
    {
      name = "es-config"
      value = jsonencode({
        cloud_id = ec_deployment.cluster.elasticsearch.cloud_id
        api_key  = elasticstack_elasticsearch_security_api_key.app.encoded
      })
    },
    {
      name = "otel-config"
      value = jsonencode({
        trace_endpoint = var.honeycombio_trace_endpoint
        meter_endpoint = var.honeycombio_meter_endpoint
        log_endpoint   = var.honeycombio_log_endpoint
        api_key        = honeycombio_api_key.this.key
      })
    },
  ]
}

data "azurerm_container_app" "api" {
  # This data source is used to get the latest revision FQDN for the container app
  # so that we can use it in the eppi-import GitHub Action.
  name                = module.container_app.container_app_name
  resource_group_name = azurerm_resource_group.this.name
  depends_on          = [module.container_app]
}

data "azurerm_container_app" "ui" {
  name                = module.container_app_ui.container_app_name
  resource_group_name = azurerm_resource_group.this.name
  depends_on          = [module.container_app_ui]
}

module "container_app" {
  source                          = "app.terraform.io/destiny-evidence/container-app/azure"
  version                         = "1.7.1"
  app_name                        = var.app_name
  cpu                             = var.container_app_cpu
  environment                     = var.environment
  container_registry_id           = data.azurerm_container_registry.this.id
  container_registry_login_server = data.azurerm_container_registry.this.login_server
  infrastructure_subnet_id        = azurerm_subnet.app.id
  memory                          = var.container_app_memory
  resource_group_name             = azurerm_resource_group.this.name
  region                          = azurerm_resource_group.this.location
  min_replicas                    = var.app_min_replicas
  max_replicas                    = var.app_max_replicas
  tags                            = local.minimum_resource_tags

  identity = {
    id           = azurerm_user_assigned_identity.container_apps_identity.id
    principal_id = azurerm_user_assigned_identity.container_apps_identity.principal_id
    client_id    = azurerm_user_assigned_identity.container_apps_identity.client_id
  }

  env_vars = concat(local.env_vars, [{
    name  = "CORS_ALLOW_ORIGINS",
    value = jsonencode(["*"])
  }])

  secrets = local.secrets

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
  version                         = "1.7.1"
  app_name                        = "${var.app_name}-task"
  cpu                             = var.container_app_tasks_cpu
  environment                     = var.environment
  container_registry_id           = data.azurerm_container_registry.this.id
  container_registry_login_server = data.azurerm_container_registry.this.login_server
  infrastructure_subnet_id        = azurerm_subnet.tasks.id
  memory                          = var.container_app_tasks_memory
  resource_group_name             = azurerm_resource_group.this.name
  region                          = azurerm_resource_group.this.location
  min_replicas                    = var.tasks_min_replicas
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

  command = ["taskiq", "worker", "app.tasks:broker", "--fs-discover", "--tasks-pattern", "app/**/tasks.py", "--max-async-tasks", var.container_app_tasks_n_concurrent_jobs]

  # Unfortunately the Azure terraform provider doesn't support setting up managed identity auth for scaling rules.
  custom_scale_rules = [
    {
      name             = "queue-length-scale-rule"
      custom_rule_type = "azure-servicebus"
      metadata = {
        namespace    = azurerm_servicebus_namespace.this.name
        queueName    = azurerm_servicebus_queue.taskiq.name
        messageCount = var.queue_active_jobs_scaling_threshold
      }
      authentication = {
        secret_name       = "servicebus-connection-string"
        trigger_parameter = "connection"
      }
    },
  ]
}

module "container_app_ui" {
  source                          = "app.terraform.io/destiny-evidence/container-app/azure"
  version                         = "1.7.1"
  app_name                        = "${var.app_name}-ui"
  environment                     = var.environment
  container_registry_id           = data.azurerm_container_registry.this.id
  container_registry_login_server = data.azurerm_container_registry.this.login_server
  infrastructure_subnet_id        = azurerm_subnet.ui.id
  resource_group_name             = azurerm_resource_group.this.name
  region                          = azurerm_resource_group.this.location
  tags                            = local.minimum_resource_tags

  identity = {
    id           = azurerm_user_assigned_identity.container_apps_ui_identity.id
    principal_id = azurerm_user_assigned_identity.container_apps_ui_identity.principal_id
    client_id    = azurerm_user_assigned_identity.container_apps_ui_identity.client_id
  }

  env_vars = [
    {
      name  = "NEXT_PUBLIC_AZURE_CLIENT_ID"
      value = azuread_application_registration.destiny_repository_auth_ui.client_id
    },
    {
      name  = "NEXT_PUBLIC_AZURE_LOGIN_URL"
      value = local.auth_login_url
    },
    {
      name  = "NEXT_PUBLIC_API_URL"
      value = "https://${data.azurerm_container_app.api.ingress[0].fqdn}/v1/"
    },
    {
      name  = "NEXT_PUBLIC_AZURE_APPLICATION_ID"
      value = azuread_application.destiny_repository.client_id
    },
  ]

  ingress = {
    external_enabled           = true
    allow_insecure_connections = false
    target_port                = 3000
    transport                  = "auto"
    traffic_weight = {
      latest_revision = true
      percentage      = 100
    }
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
  backup_retention_days         = local.is_production ? 35 : 7

  dynamic "high_availability" {
    for_each = local.is_production ? [1] : []
    content {
      mode = "ZoneRedundant"
    }
  }


  storage_mb   = local.is_development ? local.dev_db_storage_mb : local.prod_db_storage_mb
  storage_tier = local.is_development ? local.dev_db_storage_tier : local.prod_db_storage_tier

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

resource "azurerm_storage_container" "file_uploads" {
  # This is a container designed for storing user-uploaded files, such as reference files to be imported into the DESTINY repository.
  name                  = "file-uploads"
  storage_account_id    = azurerm_storage_account.this.id
  container_access_type = "private"
}

resource "azurerm_storage_container" "import_files" {
  # This is a container designed for storing pre-processed jsonl files to be imported into the DESTINY repository.
  name                  = "import-files"
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

  rule {
    name    = "delete-old-${azurerm_storage_container.file_uploads.name}-blobs"
    enabled = true
    filters {
      blob_types   = ["blockBlob"]
      prefix_match = [azurerm_storage_container.file_uploads.name]
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

  rule {
    name    = "delete-old-${azurerm_storage_container.import_files.name}-blobs"
    enabled = true
    filters {
      blob_types   = ["blockBlob"]
      prefix_match = [azurerm_storage_container.import_files.name]
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

resource "ec_deployment" "cluster" {
  name                   = "${var.app_name}-${substr(var.environment, 0, 4)}-es"
  region                 = var.elasticsearch_region
  version                = var.elastic_stack_version
  deployment_template_id = "azure-general-purpose"

  elasticsearch = {
    autoscale = true

    hot = {
      size = "2g"
      autoscaling = {
        max_size          = "30g"
        max_size_resource = "memory"
      }
    }

    warm = {
      size = "0g"
      autoscaling = {
        max_size          = "30g"
        max_size_resource = "memory"
      }
    }

    cold = {
      size = "0g"
      autoscaling = {
        max_size          = "60g"
        max_size_resource = "memory"
      }
    }

    frozen = {
      size = "0g"
      autoscaling = {
        max_size          = "60g"
        max_size_resource = "memory"
      }
    }

    ml = {
      size = "0g"
      autoscaling = {
        max_size          = "30g"
        max_size_resource = "memory"
      }
    }
  }

  kibana = {}

  observability = {
    deployment_id = "self"
    logs          = true
    metrics       = true
  }

  lifecycle {
    prevent_destroy = true
    ignore_changes = [
      elasticsearch.hot.size,
      elasticsearch.warm.size,
      elasticsearch.cold.size,
      elasticsearch.frozen.size,
      elasticsearch.ml.size
    ]
  }
}

resource "elasticstack_elasticsearch_security_api_key" "app" {
  name = "${var.app_name}-${var.environment}-app"
  role_descriptors = jsonencode({
    app_access = {
      cluster = ["monitor"]
      indices = [
        {
          names                    = local.managed_indices
          privileges               = ["read", "write", "create_index", "manage"]
          allow_restricted_indices = false
        }
      ]
    }
  })
}


resource "elasticstack_elasticsearch_security_api_key" "read_only" {
  name = "${var.app_name}-${var.environment}-read-only"
  role_descriptors = jsonencode({
    app_access = {
      cluster = ["monitor"]
      indices = [
        {
          names                    = local.managed_indices
          privileges               = ["read"]
          allow_restricted_indices = false
        }
      ]
    }
  })
}

resource "elasticstack_elasticsearch_snapshot_lifecycle" "snapshots" {
  name = "snapshot-policy"

  # Every 30 minutes for production, once a day at 01:30 AM otherwise
  schedule   = local.is_production ? "0 */30 * * * ?" : "0 30 1 * * ?"
  repository = "found-snapshots" # Default Elastic Cloud repository

  expire_after = "30d"
  min_count    = local.is_production ? 336 : 7 # 7 days worth
}

resource "azurerm_role_assignment" "es_index_migrator_acr_access" {
  principal_id         = azurerm_user_assigned_identity.es_index_migrator.principal_id
  scope                = data.azurerm_container_registry.this.id
  role_definition_name = "AcrPull"

  # terraform seems unable to replace the role assignment, so we need to ignore changes
  lifecycle {
    ignore_changes = [principal_id, scope]
  }
}

resource "elasticstack_elasticsearch_security_api_key" "es_index_migrator" {
  name = local.es_index_migrator_name
  role_descriptors = jsonencode({
    app_access = {
      cluster = ["monitor"]
      indices = [
        {
          names                    = local.managed_indices
          privileges               = ["all"]
          allow_restricted_indices = false
        }
      ]
    }
  })
}

resource "azurerm_container_app_job" "es_index_migrator" {
  name                         = local.es_index_migrator_name
  location                     = azurerm_resource_group.this.location
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = module.container_app.container_app_env_id

  replica_timeout_in_seconds = var.elasticsearch_index_migrator_timeout

  # If the replica fails, do not retry
  replica_retry_limit = 0

  manual_trigger_config {
    parallelism              = 1
    replica_completion_count = 1
  }

  registry {
    identity = azurerm_user_assigned_identity.es_index_migrator.id
    server   = data.azurerm_container_registry.this.login_server
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.es_index_migrator.id]
  }

  secret {
    name = "es-config"
    value = jsonencode({
      cloud_id = ec_deployment.cluster.elasticsearch.cloud_id
      api_key  = elasticstack_elasticsearch_security_api_key.es_index_migrator.encoded
    })
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

  template {
    container {
      image   = "mcr.microsoft.com/azuredocs/containerapps-helloworld:latest"
      name    = "${local.es_index_migrator_name}0"
      command = ["echo", "'Empty command'"]
      cpu     = 0.5
      memory  = "1Gi"

      env {
        name  = "APP_NAME"
        value = local.es_index_migrator_name
      }

      env {
        name        = "ES_CONFIG"
        secret_name = "es-config"
      }

      env {
        name        = "OTEL_CONFIG"
        secret_name = "otel-config"
      }

      env {
        name  = "ENV"
        value = var.environment
      }

      env {
        name  = "OTEL_ENABLED"
        value = var.telemetry_enabled
      }

      env {
        name  = "REINDEX_STATUS_POLLING_INTERVAL"
        value = var.es_migrator_reindex_polling_interval
      }
    }
  }

  # Allow us to update the image via github actions or the Azure Portal
  # Allow us to specify the command via the Azure Portal when triggering the job without it being overwritten
  lifecycle {
    ignore_changes = [template[0].container[0].image, template[0].container[0].command]
  }
}

locals {
  scheduled_jobs = {
    expire_pending_enhancements = {
      cron_expression = "*/10 * * * *" # Every 10 minutes
      command         = ["python", "-m", "app.run_task", "app.domain.references.tasks:expire_and_replace_stale_pending_enhancements"]
      timeout_seconds = 120
    }
  }
}

resource "azurerm_container_app_job" "scheduled_jobs" {
  for_each = local.scheduled_jobs

  name                         = "${replace(each.key, "_", "-")}-${substr(var.environment, 0, 4)}"
  location                     = azurerm_resource_group.this.location
  resource_group_name          = azurerm_resource_group.this.name
  container_app_environment_id = module.container_app.container_app_env_id

  replica_timeout_in_seconds = lookup(each.value, "timeout_seconds", 3600)
  replica_retry_limit        = lookup(each.value, "retry_limit", 1)

  tags = merge(
    local.minimum_resource_tags,
    {
      "app"         = var.app_name
      "environment" = var.environment
      "job-type"    = "scheduled"
    }
  )

  schedule_trigger_config {
    cron_expression          = each.value.cron_expression
    parallelism              = 1
    replica_completion_count = 1
  }

  registry {
    identity = azurerm_user_assigned_identity.container_apps_tasks_identity.id
    server   = data.azurerm_container_registry.this.login_server
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.container_apps_tasks_identity.id]
  }

  dynamic "secret" {
    for_each = local.secrets
    content {
      name  = secret.value.name
      value = secret.value.value
    }
  }

  template {
    container {
      image   = "${data.azurerm_container_registry.this.login_server}/destiny-repository:${var.environment}"
      name    = "${replace(each.key, "_", "-")}-${substr(var.environment, 0, 4)}"
      command = each.value.command
      cpu     = lookup(each.value, "cpu", 0.5)
      memory  = lookup(each.value, "memory", "1Gi")

      dynamic "env" {
        for_each = concat(local.env_vars, [
          {
            name  = "APP_NAME"
            value = "${var.app_name}-scheduled-job"
          },
          {
            name  = "AZURE_CLIENT_ID"
            value = azurerm_user_assigned_identity.container_apps_tasks_identity.client_id
          }
        ])
        content {
          name        = env.value.name
          value       = lookup(env.value, "value", null)
          secret_name = lookup(env.value, "secret_name", null)
        }
      }
    }
  }

  # Allow image updates via GitHub Actions deployment workflow
  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }
}
