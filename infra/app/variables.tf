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


variable "pypi_token" {
  description = "API token for PyPI"
  type        = string
  sensitive   = true
}


variable "pypi_repository" {
  description = "PyPI repository to publish to, either 'pypi' or 'testpypi'"
  type        = string
}
