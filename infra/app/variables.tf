variable "app_name" {
  type        = string
  default     = "destiny-repository"
  description = "Application Name"
}

variable "environment" {
  description = "The name of the environment this stack is being deployed to"
  type        = string
}

variable "region" {
  description = "The region resources will be deployed into"
  type        = string
}
