# Assume that an application is already registered for GitHub OIDC
# At some point we should probably create these per-environment to
# limit potential blast radius
data "azuread_application" "github-actions" {
  display_name = "GitHub Actions"
}

data "azuread_client_config" "current" {
}

# This credential means that when GitHub requests a token with a
# given environment will have the appropriate permissions
resource "azuread_application_federated_identity_credential" "github" {
  display_name = "gha-${var.app_name}-deploy-${var.environment}"

  application_id = data.azuread_application.github-actions.id
  audiences      = ["api://AzureADTokenExchange"]
  issuer         = "https://token.actions.githubusercontent.com"
  subject        = "repo:${var.github_repo}:environment:${var.environment}"
}

resource "azuread_service_principal" "github-actions" {
  client_id                    = data.azuread_application.github-actions.client_id
  app_role_assignment_required = false
  owners                       = [data.azuread_client_config.current.object_id]
  use_existing                 = true
}

# We want our GitHub Actions to be able to update the container apps
resource "azurerm_role_assignment" "gha-container-app-env-contributor" {
  role_definition_name = "Contributor"
  scope                = module.container_app.container_app_env_id
  principal_id         = azuread_service_principal.github-actions.object_id
}

# We should create a custom role which doesn't require such control
resource "azurerm_role_assignment" "gha-container-app-contributor" {
  role_definition_name = "Contributor"
  scope                = module.container_app.container_app_id
  principal_id         = azuread_service_principal.github-actions.object_id
}

resource "azurerm_role_assignment" "gha-container-app-tasks-contributor" {
  role_definition_name = "Contributor"
  scope                = module.container_app_tasks.container_app_id
  principal_id         = azuread_service_principal.github-actions.object_id
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
