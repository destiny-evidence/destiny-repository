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
  value         = azuread_application_registration.github_actions.client_id
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

resource "github_actions_environment_variable" "azure_directory_client_id" {
  environment   = github_repository_environment.environment.environment
  repository    = github_repository_environment.environment.repository
  variable_name = "AZURE_DIRECTORY_CLIENT_ID"
  value         = azuread_application_registration.github_actions.client_id
}

resource "github_actions_environment_variable" "azure_directory_tenant_id" {
  environment   = github_repository_environment.environment.environment
  repository    = github_repository_environment.environment.repository
  variable_name = "AZURE_DIRECTORY_TENANT_ID"
  value         = var.azure_tenant_id
}

resource "github_actions_environment_variable" "azure_login_url" {
  environment   = github_repository_environment.environment.environment
  repository    = github_repository_environment.environment.repository
  variable_name = "AZURE_LOGIN_URL"
  value         = local.auth_login_url
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

resource "github_actions_environment_variable" "container_app_tasks_name" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "CONTAINER_APP_TASKS_NAME"
  value         = module.container_app_tasks.container_app_name
}

# --- UI ---
# The UI is a static bundle: Vite inlines the UI_* values at build time, and
# the rest tell the deploy where to upload it and which cache to purge.

resource "github_actions_environment_variable" "ui_storage_account_name" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "UI_STORAGE_ACCOUNT_NAME"
  value         = azurerm_storage_account.ui.name
}

resource "github_actions_environment_variable" "ui_api_base" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "UI_API_BASE"
  value         = "https://${local.api_hostname}/v1"
}

resource "github_actions_environment_variable" "ui_keycloak_url" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "UI_KEYCLOAK_URL"
  value         = var.shared_keycloak_url
}

resource "github_actions_environment_variable" "ui_keycloak_realm" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "UI_KEYCLOAK_REALM"
  value         = "destiny"
}

resource "github_actions_environment_variable" "ui_keycloak_client_id" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "UI_KEYCLOAK_CLIENT_ID"
  value         = "destiny-auth-ui-client-${var.environment}"
}

resource "github_actions_environment_variable" "ui_custom_domain" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "UI_CUSTOM_DOMAIN"
  value         = local.ui_hostname
}

resource "github_actions_environment_variable" "frontdoor_resource_group" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "FRONTDOOR_RESOURCE_GROUP"
  value         = var.shared_resource_group_name
}

resource "github_actions_environment_variable" "frontdoor_profile_name" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "FRONTDOOR_PROFILE_NAME"
  value         = data.azurerm_cdn_frontdoor_profile.shared.name
}

resource "github_actions_environment_variable" "frontdoor_endpoint_name" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "FRONTDOOR_ENDPOINT_NAME"
  value         = local.frontdoor_endpoint.name
}

resource "github_actions_environment_variable" "container_app_env" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "CONTAINER_APP_ENV"
  value         = module.container_app.container_app_env_name
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

resource "github_actions_environment_variable" "destiny_api_identifier_uri" {
  # The Destiny API identifier URI is used by the eppi-import GitHub Action
  # to generate an access token for the Destiny API so it can import references.
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "DESTINY_API_IDENTIFIER_URI"
  value         = azuread_application_identifier_uri.this.identifier_uri
}

resource "github_actions_environment_variable" "pypi_repository" {
  repository    = github_repository_environment.environment.repository
  environment   = github_repository_environment.environment.environment
  variable_name = "PYPI_REPOSITORY"
  value         = var.pypi_repository
}

resource "github_actions_environment_secret" "azure_storage_account_name" {
  # The eppi-import GitHub Action needs to be able to upload the processed
  # JSONL file to the storage account.
  repository      = github_repository_environment.environment.repository
  environment     = github_repository_environment.environment.environment
  secret_name     = "AZURE_STORAGE_ACCOUNT_NAME"
  plaintext_value = azurerm_storage_account.this.name
}

resource "github_actions_environment_secret" "ci_slack_webhook_url" {
  # Read by the notify step in deploy.yml to announce production deploys.
  repository      = github_repository_environment.environment.repository
  environment     = github_repository_environment.environment.environment
  secret_name     = "CI_SLACK_WEBHOOK_URL"
  plaintext_value = var.ci_slack_webhook_url
}

resource "github_actions_environment_secret" "destiny_api_endpoint" {
  # The eppi-import GitHub Action needs know the url to the Destiny API.
  repository      = github_repository_environment.environment.repository
  environment     = github_repository_environment.environment.environment
  secret_name     = "DESTINY_API_ENDPOINT"
  plaintext_value = "https://${local.api_hostname}/v1/"
}
