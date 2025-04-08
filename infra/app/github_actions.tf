# A reference to the subscription currently used by the Azure
# Resource Manager provider
data "azurerm_subscription" "current" {
}

# A GitHub repository environment is a collection of variables
# and secrets associated with a given deployment. This allows
# us to use the same workflow but with different variables
# per environment.

# We are actively choosing to duplicate all variables across
# environments to avoid conflicts over shared variables (like
# Azure client ids)
resource "github_repository_environment" "environment" {
  repository  = var.app_name
  environment = var.environment
}

resource "github_actions_environment_variable" "container_registry_name" {
  environment   = github_repository_environment.environment.environment
  repository    = github_repository_environment.environment.repository
  variable_name = "REGISTRY_NAME"
  value         = data.azurerm_container_registry.this.name
}

resource "github_actions_environment_variable" "azure_client_id" {
  environment   = github_repository_environment.environment.environment
  repository    = github_repository_environment.environment.repository
  variable_name = "AZURE_CLIENT_ID"
  value         = data.azuread_application.github-actions.client_id
}

resource "github_actions_environment_variable" "azure_subscription_id" {
  environment   = github_repository_environment.environment.environment
  repository    = github_repository_environment.environment.repository
  variable_name = "AZURE_SUBSCRIPTION_ID"
  value         = data.azurerm_subscription.current.subscription_id
}

resource "github_actions_environment_variable" "azure_tenant_id" {
  environment   = github_repository_environment.environment.environment
  repository    = github_repository_environment.environment.repository
  variable_name = "AZURE_TENANT_ID"
  value         = data.azurerm_subscription.current.tenant_id
}

resource "github_actions_environment_variable" "app_name" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "APP_NAME"
  value         = var.app_name
}

resource "github_actions_environment_variable" "container_app_name" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "CONTAINER_APP_NAME"
  value         = module.container_app.container_app_name
}

resource "github_actions_environment_variable" "container_app_name" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "CONTAINER_APP_NAME"
  value         = module.container_app.container_app_name
}

resource "github_actions_environment_variable" "container_app_tasks_name" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "CONTAINER_APP_TASKS_NAME"
  value         = module.container_app_tasks.container_app_name
}

resource "github_actions_environment_variable" "github_environment_name" {
  # Part of a workaround where environment name isn't present in github action workflow contexts
  # https://docs.github.com/en/actions/writing-workflows/choosing-what-your-workflow-does/accessing-contextual-information-about-workflow-runs#about-contexts
  environment   = github_repository_environment.environment.environment
  repository    = github_repository_environment.environment.repository
  variable_name = "ENVIRONMENT_NAME"
  value         = github_repository_environment.environment.environment
}

resource "github_actions_environment_variable" "resource_group" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "RESOURCE_GROUP"
  value         = azurerm_resource_group.this.name
}
