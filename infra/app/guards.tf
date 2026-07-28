/** Plan-time guardrails. */

# --- Guardrail: Container App Environment Consumption CPU budget ---
# Every app and job here shares one Consumption workload profile, capped at a
# fixed number of *requested* CPU cores (not used ones). This asserts the worst-case
# deploy draw stays under the quota.
locals {
  # The Consumption profile's requested-CPU ceiling.
  consumption_core_quota = 100

  # A rolling deploy runs old and new revisions concurrently, so the scalable
  # apps can transiently request up to 2x their steady-state cores.
  rollout_factor = 2

  # The UI app's replicas/CPU live in the remote container-app module and aren't
  # exposed as root variables; reserve a rollout-inclusive allowance.
  ui_reserved_cores = 4

  scalable_app_cores = (
    var.app_max_replicas * var.container_app_cpu +
    var.tasks_max_replicas * var.container_app_tasks_cpu
  )

  # Worst case: every container app job runs at once. A job's draw is its
  # parallelism (concurrent replicas per execution) x per-replica CPU.
  scheduled_job_cores = length(azurerm_container_app_job.scheduled_jobs) > 0 ? sum([
    for job in azurerm_container_app_job.scheduled_jobs :
    job.schedule_trigger_config[0].parallelism * job.template[0].container[0].cpu
  ]) : 0

  job_cores = (
    azurerm_container_app_job.database_migrator.manual_trigger_config[0].parallelism *
    azurerm_container_app_job.database_migrator.template[0].container[0].cpu
    +
    azurerm_container_app_job.es_index_migrator.manual_trigger_config[0].parallelism *
    azurerm_container_app_job.es_index_migrator.template[0].container[0].cpu
    +
    local.scheduled_job_cores
  )

  worst_case_deploy_cores = (
    local.rollout_factor * local.scalable_app_cores +
    local.job_cores +
    local.ui_reserved_cores
  )
}

# --- Registry ---
# Each entry is a precondition spec: a condition that must hold, and the message
# shown when it doesn't.
locals {
  guardrails = {
    consumption_cpu_budget = {
      condition = local.worst_case_deploy_cores <= local.consumption_core_quota
      error_message = format(
        "Worst-case deploy draw is %g cores (%dx scalable apps = %g, jobs = %g, UI reserve = %g) but the Consumption quota is %d. Lower tasks_max_replicas / app_max_replicas or per-replica CPU.",
        local.worst_case_deploy_cores,
        local.rollout_factor,
        local.rollout_factor * local.scalable_app_cores,
        local.job_cores,
        local.ui_reserved_cores,
        local.consumption_core_quota,
      )
    }
  }
}

# --- Enforcement ---
# One precondition per registered guardrail
resource "terraform_data" "guardrail" {
  for_each = local.guardrails

  lifecycle {
    precondition {
      condition     = each.value.condition
      error_message = each.value.error_message
    }
  }
}
