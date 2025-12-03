# Unique UUIDs for app roles (application permissions)
resource "random_uuid" "administrator_role" {}
resource "random_uuid" "importer_role" {}
resource "random_uuid" "reference_reader_role" {}
resource "random_uuid" "reference_deduplicator_role" {}
resource "random_uuid" "robot_writer_role" {}
resource "random_uuid" "enhancement_request_writer_role" {}

# Unique UUIDs for oauth2_permission_scope (delegated permissions)
resource "random_uuid" "administrator_scope" {}
resource "random_uuid" "importer_scope" {}
resource "random_uuid" "reference_reader_scope" {}
resource "random_uuid" "reference_deduplicator_scope" {}
resource "random_uuid" "robot_writer_scope" {}
resource "random_uuid" "enhancement_request_writer_scope" {}

# AD application for destiny repository
# App scopes to allow various functions (i.e. imports) should be added as oauth2_permission_scope here
resource "azuread_application" "destiny_repository" {
  display_name     = local.name
  sign_in_audience = "AzureADMyOrg"

  api {
    oauth2_permission_scope {
      admin_consent_description  = "Allow the app to administer the system as the signed-in user"
      admin_consent_display_name = "Administrator as user"
      id                         = random_uuid.administrator_scope.result
      type                       = "User"
      value                      = "administrator.all"
      user_consent_description   = "Allow you to administer the system"
      user_consent_display_name  = "Administrator"
    }

    oauth2_permission_scope {
      admin_consent_description  = "Allow the app to import as the signed-in user"
      admin_consent_display_name = "Import as user"
      id                         = random_uuid.importer_scope.result
      type                       = "User"
      value                      = "import.writer.all"
      user_consent_description   = "Allow you to import"
      user_consent_display_name  = "Import"
    }

    oauth2_permission_scope {
      admin_consent_description  = "Allow the app to view references as the signed-in user"
      admin_consent_display_name = "Reference Reader as user"
      id                         = random_uuid.reference_reader_scope.result
      type                       = "User"
      value                      = "reference.reader.all"
      user_consent_description   = "Allow you to view references"
      user_consent_display_name  = "Reference Reader"
    }
    oauth2_permission_scope {
      admin_consent_description  = "Allow the app to deduplicate references as the signed-in user"
      admin_consent_display_name = "Reference Deduplicator as user"
      id                         = random_uuid.reference_deduplicator_scope.result
      type                       = "User"
      value                      = "reference.deduplicator.all"
      user_consent_description   = "Allow you to deduplicate references"
      user_consent_display_name  = "Reference Deduplicator"
    }

    oauth2_permission_scope {
      admin_consent_description  = "Allow the app to request enhancements as the signed-in user"
      admin_consent_display_name = "Enhancement Request Writer as user"
      id                         = random_uuid.enhancement_request_writer_scope.result
      type                       = "User"
      value                      = "enhancement_request.writer.all"
      user_consent_description   = "Allow you to request enhancements"
      user_consent_display_name  = "Enhancement Request Writer"
    }

    oauth2_permission_scope {
      admin_consent_description  = "Allow the app to register robots and rotate robot client secrets as the signed-in user"
      admin_consent_display_name = "Robot Writer as user"
      id                         = random_uuid.robot_writer_scope.result
      type                       = "User"
      value                      = "robot.writer.all"
      user_consent_description   = "Allow you to register robots and rotate robot client secrets"
      user_consent_display_name  = "Robot Writer"
    }
  }

  lifecycle {
    # this prevents changes in this resource clearing the ones defined below
    ignore_changes = [
      identifier_uris,
      app_role
    ]
  }
}

resource "azuread_application_app_role" "administrator" {
  application_id       = azuread_application.destiny_repository.id
  allowed_member_types = ["Application"]
  description          = "Can manage the repository itself"
  display_name         = "Administrator"
  role_id              = random_uuid.administrator_role.result
  value                = "administrator"
}

resource "azuread_application_app_role" "importer" {
  application_id       = azuread_application.destiny_repository.id
  allowed_member_types = ["Application"]
  description          = "Importers can import"
  display_name         = "Importers"
  role_id              = random_uuid.importer_role.result
  value                = "import.writer"
}

resource "azuread_application_app_role" "reference_reader" {
  application_id       = azuread_application.destiny_repository.id
  allowed_member_types = ["Application"]
  description          = "Can view references"
  display_name         = "Reference Reader"
  role_id              = random_uuid.reference_reader_role.result
  value                = "reference.reader"
}

resource "azuread_application_app_role" "reference_deduplicator" {
  application_id       = azuread_application.destiny_repository.id
  allowed_member_types = ["Application"]
  description          = "Can deduplicate references"
  display_name         = "Reference Deduplicator"
  role_id              = random_uuid.reference_deduplicator_role.result
  value                = "reference.deduplicator"
}

resource "azuread_application_app_role" "enhancement_request_writer" {
  application_id       = azuread_application.destiny_repository.id
  allowed_member_types = ["Application"]
  description          = "Can request enhancements"
  display_name         = "Enhancement Request Writer"
  role_id              = random_uuid.enhancement_request_writer_role.result
  value                = "enhancement_request.writer"
}

resource "azuread_service_principal" "destiny_repository" {
  client_id                    = azuread_application.destiny_repository.client_id
  app_role_assignment_required = false
  owners                       = [data.azuread_client_config.current.object_id]
}

resource "azuread_application_identifier_uri" "this" {
  application_id = azuread_application.destiny_repository.id
  identifier_uri = "api://${azuread_application.destiny_repository.client_id}"
}

# Grant the GitHub Actions service principal the importer role so it can run the eppi-import GitHub Action
resource "azuread_app_role_assignment" "github_actions_to_importer" {
  app_role_id         = azuread_application_app_role.importer.role_id
  principal_object_id = azuread_service_principal.github_actions.object_id
  resource_object_id  = azuread_service_principal.destiny_repository.object_id
}

resource "azuread_application_api_access" "github_actions" {
  application_id = azuread_application_registration.github_actions.id
  api_client_id  = azuread_application.destiny_repository.client_id

  role_ids = [
    azuread_application_app_role.importer.role_id
  ]
}

# Create an application that we can use to authenticate with the Destiny Repository
resource "azuread_application_registration" "destiny_repository_auth" {
  display_name                   = "${local.name}-auth-client"
  sign_in_audience               = "AzureADMyOrg"
  requested_access_token_version = 2
}

resource "azuread_application_api_access" "destiny_repository_auth" {
  application_id = azuread_application_registration.destiny_repository_auth.id
  api_client_id  = azuread_application.destiny_repository.client_id

  scope_ids = [
    random_uuid.administrator_scope.result,
    random_uuid.importer_scope.result,
    random_uuid.reference_reader_scope.result,
    random_uuid.enhancement_request_writer_scope.result,
    random_uuid.robot_writer_scope.result,
    random_uuid.reference_deduplicator_scope.result,
  ]
}


resource "azuread_application_registration" "destiny_repository_auth_ui" {
  display_name                   = "${local.name}-auth-ui-client"
  sign_in_audience               = "AzureADMyOrg"
  requested_access_token_version = 2
}

resource "azuread_application_api_access" "destiny_repository_auth_ui" {
  application_id = azuread_application_registration.destiny_repository_auth_ui.id
  api_client_id  = azuread_application.destiny_repository.client_id

  scope_ids = [
    random_uuid.reference_reader_scope.result,
  ]
}

# This group is managed by click-ops in Entra Id
# Allow group members to authenticate via the auth client
resource "azuread_app_role_assignment" "developer_to_auth" {
  app_role_id         = "00000000-0000-0000-0000-000000000000"
  principal_object_id = var.developers_group_id
  resource_object_id  = azuread_service_principal.destiny_repository_auth.object_id
}


resource "azuread_app_role_assignment" "ui_users_to_auth_ui" {
  app_role_id         = "00000000-0000-0000-0000-000000000000"
  principal_object_id = var.ui_users_group_id
  resource_object_id  = azuread_service_principal.destiny_repository_auth_ui.object_id
}

resource "azuread_service_principal" "destiny_repository_auth" {
  client_id                    = azuread_application_registration.destiny_repository_auth.client_id
  app_role_assignment_required = true
  owners                       = [data.azuread_client_config.current.object_id]
}

resource "azuread_service_principal" "destiny_repository_auth_ui" {
  client_id                    = azuread_application_registration.destiny_repository_auth_ui.client_id
  app_role_assignment_required = true
  owners                       = [data.azuread_client_config.current.object_id]
}

resource "azuread_application_redirect_uris" "local_redirect" {
  # This is necessary to return the token to you if you're grabbing a token for local dev
  application_id = azuread_application_registration.destiny_repository_auth.id
  type           = "PublicClient"

  redirect_uris = var.local_redirect_urls
}

resource "azuread_application_redirect_uris" "ui_redirect" {
  # This is necessary to return the token to the UI
  application_id = azuread_application_registration.destiny_repository_auth_ui.id
  type           = "SPA"

  redirect_uris = [
    "https://${data.azurerm_container_app.ui.ingress[0].fqdn}",
  ]
}

resource "azuread_application_redirect_uris" "ui_public_client_redirect" {
  # This is necessary to return the token to the user when using PublicClient flow
  application_id = azuread_application_registration.destiny_repository_auth_ui.id
  type           = "PublicClient"

  redirect_uris = var.local_redirect_urls
}

# Openalex incremental updater role assignments
data "azuread_application" "openalex_incremental_updater" {
  client_id = var.open_alex_incremental_updater_client_id
}

resource "azuread_application_api_access" "openalex_incremental_updater" {
  application_id = data.azuread_application.openalex_incremental_updater.id
  api_client_id  = azuread_application.destiny_repository.client_id

  # Only importer role
  role_ids = [
    azuread_application_app_role.importer.role_id
  ]
}

# DESTINY UI role assignments
# Note: this is a separate app, not the inbuilt repository UI
data "azurerm_user_assigned_identity" "destiny_ui" {
  name                = var.destiny_ui_app_name
  resource_group_name = "rg-${var.destiny_ui_app_name}-${var.environment}"
}

resource "azuread_app_role_assignment" "destiny_ui_to_reference_reader" {
  app_role_id         = azuread_application_app_role.reference_reader.role_id
  principal_object_id = data.azurerm_user_assigned_identity.destiny_ui.principal_id
  resource_object_id  = azuread_service_principal.destiny_repository.object_id
}
