variable "app_name" {
  type        = string
  default     = "destiny-repository"
  description = "Application Name"
}

variable "admin_login" {
  type        = string
  description = "admin login for the app database"
}

variable "admin_password" {
  type        = string
  description = "admin password for the app database"
  sensitive   = true
}

variable "app_min_replicas" {
  description = "Minimum number of replicas for the app container app"
  type        = number
  default     = 2
}

variable "tasks_min_replicas" {
  description = "Minimum number of replicas for the tasks container app"
  type        = number
  default     = 2
}

variable "app_max_replicas" {
  description = "Maximum number of replicas for the app container app"
  type        = number
  default     = 10
}

variable "tasks_max_replicas" {
  description = "Maximum number of replicas for the tasks container app"
  type        = number
  default     = 10
}

variable "azure_tenant_id" {
  description = "ID of the azure application "
  type        = string
}

variable "external_directory_enabled" {
  description = "Enable authentication via the external directory (CIAM). When false, uses the application tenant for authentication."
  type        = bool
  default     = false
}

variable "external_directory_tenant_id" {
  description = "ID of the external directory tenant for the Azure AD provider. Required when external_directory_enabled is true."
  type        = string
}

variable "azure_login_url" {
  description = "Azure login URL for JWT token validation. Required when external_directory_enabled is true. Examples: https://login.microsoftonline.com/tenantId, https://tenantName.ciamlogin.com/tenantId"
  type        = string
  default     = null
}

variable "budget_code" {
  description = "Budget code for tagging resource groups. Required tag for resource groups"
  type        = string
}


variable "container_app_cpu" {
  description = "CPU for the app container app"
  type        = number
  default     = 0.5
}

variable "container_app_memory" {
  description = "Memory for the app container app"
  type        = string
  default     = "1Gi"
}

variable "container_app_tasks_cpu" {
  description = "CPU for the tasks container app"
  type        = number
  default     = 0.5
}

variable "container_app_tasks_memory" {
  description = "Memory for the tasks container app"
  type        = string
  default     = "1Gi"
}

variable "container_app_tasks_n_concurrent_jobs" {
  description = "Number of concurrent jobs for the tasks container app"
  type        = number
  default     = 4
}

variable "container_registry_name" {
  description = "The name of the container registry being used"
  type        = string
}

variable "container_registry_resource_group" {
  description = "The name of the resource group the container registry is in"
  type        = string
}

variable "cpu_scaling_threshold" {
  description = "CPU threshold for scaling the app container app"
  type        = number
  default     = 70
}

variable "queue_active_jobs_scaling_threshold" {
  description = "Active jobs threshold for scaling the tasks container app"
  type        = number
  default     = 100
}

variable "created_by" {
  description = "Who created this infrastrcuture. Required tag for resource groups"
  type        = string
}

variable "developers_group_id" {
  type        = string
  description = "Id of a group to assign to all API roles on destiny repository, allowing api authentication for devs"
}

variable "external_directory_developers_group_id" {
  type        = string
  description = "Id of a group to assign to all API roles on destiny repository, allowing api authentication for devs. Required when external_directory_enabled is true."
}

variable "external_directory_client_id" {
  description = "Client ID of the external directory application. Required when external_directory_enabled is true."
  type        = string
}

variable "ui_users_group_id" {
  type        = string
  description = "Id of a group to assign to UI-relevant API roles on destiny repository"
}

variable "external_directory_ui_users_group_id" {
  type        = string
  description = "Id of a group to assign to UI-relevant API roles on destiny repository. Required when external_directory_enabled is true."
}

variable "db_crud_group_id" {
  type        = string
  description = "Id of a group to assign DB crud access to. Not exclusive to other DB groups."
}

variable "db_admin_group_id" {
  type        = string
  description = "Id of a group to assign DB admin access to. Not exclusive to other DB groups."
}

variable "environment" {
  description = "The name of the environment this stack is being deployed to"
  type        = string
}

variable "github_app_id" {
  description = "The app id for GitHub app used to configure github"
  type        = string
}

variable "github_app_installation_id" {
  description = "The app installation ID for the GitHub App used to configure github"
  type        = string
}

variable "github_app_pem" {
  description = "The app pem file for authenticating as a GitHub App"
  type        = string
  sensitive   = true
}

variable "github_repo" {
  type        = string
  default     = "destiny-evidence/destiny-repository"
  description = "GitHub repo to use for GitHub Actions"
}

variable "owner" {
  description = "Email of the owner of this infrastructure. Required tag for resource groups"
  type        = string
}

variable "project" {
  description = "Email of the owner of this infrastructure. Required tag for resource groups"
  type        = string
}

variable "region" {
  description = "The region resources will be deployed into"
  type        = string
}

variable "open_alex_incremental_updater_client_id" {
  description = "The client id of the open alex incrememtal updater application"
  type        = string
}

variable "open_alex_incremental_updater_external_client_id" {
  description = "The client id of the open alex incrememtal updater application in the external tenant. Required when external_directory_enabled is true."
  type        = string
}

variable "destiny_demonstrator_ui_app_name" {
  description = "The name of the destiny demonstrator ui application"
  type        = string
  default     = "demonstrator-ui"
}

variable "elasticsearch_sku" {
  description = "SKU for the Elasticsearch cluster"
  type        = string
  default     = "ess-consumption-2024_Monthly"
}

variable "elasticsearch_admin_email" {
  description = "Email address for the Elasticsearch admin user"
  type        = string
}

# elasticsearch is not available in all regions, see https://www.elastic.co/cloud/regions
variable "elasticsearch_region" {
  description = "Region for the Elasticsearch cluster"
  type        = string
  default     = "azure-westeurope"
}

variable "elastic_stack_version" {
  description = "Version of the Elastic Stack to use"
  type        = string
  default     = "9.0.2"
}

variable "elastic_cloud_apikey" {
  description = "API key for the Elastic Cloud provider"
  type        = string
  sensitive   = true
}

variable "elasticsearch_index_migrator_timeout" {
  description = "How long to wait for an ES index migration to complete when running a container app job in seconds"
  type        = number
  default     = 28800 # 8 hour timeout
}


variable "pypi_token" {
  description = "API token for PyPI"
  type        = string
  sensitive   = true
}


variable "pypi_repository" {
  description = "PyPI repository to publish to, either 'pypi' or 'testpypi'"
  type        = string
}


variable "honeycombio_api_key_id" {
  description = "API key id for Honeycomb.io"
  type        = string
  sensitive   = true
}

variable "honeycombio_api_key_secret" {
  description = "API key secret for Honeycomb.io"
  type        = string
  sensitive   = true
}

variable "honeycombio_configuration_api_key" {
  description = "Configuration API key for Honeycomb.io"
  type        = string
  sensitive   = true
}

variable "honeycombio_trace_endpoint" {
  description = "Trace endpoint for Honeycomb.io"
  type        = string
  default     = "https://api.honeycomb.io/v1/traces"
}

variable "honeycombio_meter_endpoint" {
  description = "Meter endpoint for Honeycomb.io"
  type        = string
  default     = "https://api.honeycomb.io/v1/metrics"
}

variable "honeycombio_log_endpoint" {
  description = "Logging endpoint for Honeycomb.io"
  type        = string
  default     = "https://api.honeycomb.io/v1/logs"
}

variable "telemetry_enabled" {
  description = "Whether telemetry is enabled for the application"
  type        = bool
  default     = true
}

variable "honeycomb_alert_slack_channel" {
  description = "Slack channel for Honeycomb alerts"
  type        = string
  default     = "#destiny-alerts"
}

variable "feature_flags" {
  description = "Feature flags for the application"
  type        = map(bool)
  default     = {}
}

variable "default_upload_file_chunk_size" {
  description = "Default number of entries to write per file upload chunk"
  type        = number
  default     = 1
}

variable "max_reference_lookup_query_length" {
  description = "Maximum number of identifiers to allow in a single reference lookup query"
  type        = number
  default     = 100
}

variable "es_migrator_reindex_polling_interval" {
  description = "How frequently to poll the reindexing task when migrating indices"
  type        = number
  default     = 5 * 60 # 5min

}

variable "message_lock_renewal_duration" {
  description = "Duration to renew message locks for in seconds"
  type        = number
  default     = 12 * 60 * 60 # 12 hours
}

variable "trusted_unique_identifier_types" {
  description = "External identifier types that are certain to be unique. Used for shortcutting deduplication."
  type        = list(string)
  default     = []
}
