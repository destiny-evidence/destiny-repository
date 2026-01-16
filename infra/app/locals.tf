locals {
  name                   = "${var.app_name}-${var.environment}"
  es_index_migrator_name = "es-index-migrator-${var.environment}"
  # var.app_name-* can be removed the list below after we migrate to versioned indicies
  managed_indices = [
    "${var.app_name}-*",
    "reference*",
    "robot-automation-percolation*"
  ]
  is_production  = var.environment == "production"
  is_development = var.environment != "production" && var.environment != "staging"

  minimum_resource_tags = {
    # All these tags are required for UCL tenant compliance policies
    "Created by"  = var.created_by,
    "Environment" = var.environment
    "Owner"       = var.owner
    "Project"     = var.project
    "Region"      = var.region
  }

  redirect_uris = [
    "http://localhost",
    "https://oauth.pstmn.io/v1/callback",
  ]
}
