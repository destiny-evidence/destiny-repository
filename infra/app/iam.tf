data "azuread_client_config" "current" {
}

resource "azuread_application_registration" "github_actions" {
  display_name     = "github-actions-${local.name}"
  sign_in_audience = "AzureADMyOrg"
}

resource "azuread_service_principal" "github_actions" {
  client_id                    = azuread_application_registration.github_actions.client_id
  app_role_assignment_required = true
  owners                       = [data.azuread_client_config.current.object_id]
}

# This credential means that when GitHub requests a token with a
# given environment will have the appropriate permissions
resource "azuread_application_federated_identity_credential" "github" {
  display_name = "gha-${var.app_name}-deploy-${var.environment}"

  application_id = azuread_application_registration.github_actions.id
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_repo}:environment:${var.environment}"
}

resource "azuread_application_registration" "external_directory_github_actions" {
  provider                       = azuread.external_directory
  display_name                   = "github-actions-${local.name}"
  sign_in_audience               = "AzureADMyOrg"
  requested_access_token_version = 2
}

resource "azuread_service_principal" "external_directory_github_actions" {
  provider                     = azuread.external_directory
  client_id                    = azuread_application_registration.external_directory_github_actions.client_id
  app_role_assignment_required = true
  owners                       = [data.azuread_client_config.external_directory.object_id]
}

# This credential means that when GitHub requests a token with a
# given environment will have the appropriate permissions
resource "azuread_application_federated_identity_credential" "external_directory_github" {
  provider     = azuread.external_directory
  display_name = "gha-${var.app_name}-deploy-${var.environment}"

  application_id = azuread_application_registration.external_directory_github_actions.id
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_repo}:environment:${var.environment}"
}

# We want our Github actions to be able to push to the container registry
resource "azurerm_role_assignment" "gha-container-push" {
  role_definition_name = "AcrPush"
  scope                = data.azurerm_container_registry.this.id
  principal_id         = azuread_service_principal.github_actions.object_id
}

# We want our Github actions to be able to pull from the container registry
resource "azurerm_role_assignment" "gha-container-pull" {
  role_definition_name = "AcrPull"
  scope                = data.azurerm_container_registry.this.id
  principal_id         = azuread_service_principal.github_actions.object_id
}

# We want our GitHub Actions to be able to update the container apps
resource "azurerm_role_assignment" "gha-container-app-env-contributor" {
  role_definition_name = "Contributor"
  scope                = module.container_app.container_app_env_id
  principal_id         = azuread_service_principal.github_actions.object_id
}

# We should create a custom role which doesn't require such control
resource "azurerm_role_assignment" "gha-container-app-contributor" {
  role_definition_name = "Contributor"
  scope                = module.container_app.container_app_id
  principal_id         = azuread_service_principal.github_actions.object_id
}

resource "azurerm_role_assignment" "gha-container-app-tasks-contributor" {
  role_definition_name = "Contributor"
  scope                = module.container_app_tasks.container_app_id
  principal_id         = azuread_service_principal.github_actions.object_id
}

resource "azurerm_role_assignment" "gha-container-app-ui-contributor" {
  role_definition_name = "Contributor"
  scope                = module.container_app_ui.container_app_id
  principal_id         = azuread_service_principal.github_actions.object_id
}

resource "azurerm_role_assignment" "gha-resource-group-reader" {
  role_definition_name = "Reader"
  scope                = azurerm_resource_group.this.id
  principal_id         = azuread_service_principal.github_actions.object_id
}

resource "azurerm_role_assignment" "gha-db-migrator-contributor" {
  role_definition_name = "Contributor"
  scope = azurerm_container_app_job.database_migrator.id
  principal_id = azuread_service_principal.github_actions.object_id
}

resource "azurerm_role_assignment" "gha-scheduled-jobs-contributor" {
  for_each             = azurerm_container_app_job.scheduled_jobs
  role_definition_name = "Contributor"
  scope                = each.value.id
  principal_id         = azuread_service_principal.github_actions.object_id
}

# The eppi-import GitHub Action needs to be able to upload the processed
# JSONL file to the storage account.
resource "azurerm_role_assignment" "gha_storage_blob_contributor" {
  role_definition_name = "Storage Blob Data Contributor"
  scope                = azurerm_storage_account.this.id
  principal_id         = azuread_service_principal.github_actions.object_id
}

# The eppi-import GitHub Action needs to be able to generate a user delegation
# SAS token for the uploaded blob, so the Destiny API can read it.
resource "azurerm_role_assignment" "gha_storage_blob_delegator" {
  role_definition_name = "Storage Blob Delegator"
  scope                = azurerm_storage_account.this.id
  principal_id         = azuread_service_principal.github_actions.object_id
}

resource "azurerm_role_assignment" "service_bus_receiver" {
  role_definition_name = "Azure Service Bus Data Receiver"
  scope                = azurerm_servicebus_namespace.this.id
  principal_id         = azurerm_user_assigned_identity.container_apps_tasks_identity.principal_id
}

resource "azurerm_role_assignment" "app_service_bus_sender" {
  scope                = azurerm_servicebus_namespace.this.id
  role_definition_name = "Azure Service Bus Data Sender"
  principal_id         = azurerm_user_assigned_identity.container_apps_identity.principal_id
}

resource "azurerm_role_assignment" "tasks_service_bus_sender" {
  role_definition_name = "Azure Service Bus Data Sender"
  scope                = azurerm_servicebus_namespace.this.id
  principal_id         = azurerm_user_assigned_identity.container_apps_tasks_identity.principal_id
}
