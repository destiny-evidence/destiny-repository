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
  is_development = var.environment == "development"

  prod_db_storage_mb = 65536
  dev_db_storage_mb  = 32768

  # IPOS tiers for postgresql flexible server
  # We use the default for our storage size as defined at
  # https://registry.terraform.io/providers/hashicorp/azurerm/latest/docs/resources/postgresql_flexible_server#storage_tier-defaults-based-on-storage_mb
  prod_db_storage_tier = "P6"
  dev_db_storage_tier  = "P4"

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
    "https://${var.external_directory_tenant_id}.ciamlogin.com/${var.external_directory_tenant_id}/federation/oauth2"
  ]
}
