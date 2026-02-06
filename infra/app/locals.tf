locals {
  name                   = "${var.app_name}-${var.environment}"
  es_index_migrator_name = "es-index-migrator-${var.environment}"
  # var.app_name-* can be removed the list below after we migrate to versioned indicies
  managed_indices = [
    "${var.app_name}-*",
    "reference*",
    "robot-automation-percolation*"
  ]

  environment_configs = {
    development = {
      db_storage_mb   = 32768 # 32GB
      db_storage_tier = "P4"
      db_backup_days  = 7
      db_ha_enabled   = false

      alerts_enabled = false

      es_snapshot_schedule  = "0 30 1 * * ?" # Daily at 01:30
      es_snapshot_retention = 7
    }

    staging = {
      db_storage_mb   = 131072 # 128GB
      db_storage_tier = "P10"
      db_backup_days  = 7
      db_ha_enabled   = false

      alerts_enabled          = true
      db_storage_warning_pct  = 70
      db_storage_critical_pct = 85
      db_cpu_warning_pct      = 80
      db_cpu_critical_pct     = 90
      db_memory_warning_pct   = 80
      db_memory_critical_pct  = 90

      es_snapshot_schedule  = "0 30 1 * * ?"
      es_snapshot_retention = 7
    }

    production = {
      db_storage_mb   = 131072 # 128GB
      db_storage_tier = "P10"
      db_backup_days  = 35
      db_ha_enabled   = true

      alerts_enabled          = true
      db_storage_warning_pct  = 70
      db_storage_critical_pct = 85
      db_cpu_warning_pct      = 70
      db_cpu_critical_pct     = 85
      db_memory_warning_pct   = 70
      db_memory_critical_pct  = 85

      es_snapshot_schedule  = "0 30 1 * * ?" # Daily at 01:30
      es_snapshot_retention = 30             # 30 days
    }
  }

  # Active environment configuration (defaults to development for unknown environments)
  env = lookup(local.environment_configs, var.environment, local.environment_configs["development"])

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
