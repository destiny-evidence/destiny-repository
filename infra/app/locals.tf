locals {
  name                   = "${var.app_name}-${var.environment}"
  es_index_migrator_name = "es-index-migrator-${var.environment}"
  is_production          = var.environment == "production"
  minimum_resource_tags = {
    # All these tags are required for UCL tenant compliance policies
    "Created by"  = var.created_by,
    "Environment" = var.environment
    "Owner"       = var.owner
    "Project"     = var.project
    "Region"      = var.region
  }
}
