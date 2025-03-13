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

variable "environment" {
  description = "The name of the environment this stack is being deployed to"
  type        = string
}

variable "region" {
  description = "The region resources will be deployed into"
  type        = string
}
