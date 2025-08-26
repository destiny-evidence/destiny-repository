data "azuread_client_config" "external_directory" {
  provider = azuread.external_directory
}

# Unique UUIDs for app roles (application permissions)
resource "random_uuid" "external_directory_administrator_role" {}
resource "random_uuid" "external_directory_importer_role" {}
resource "random_uuid" "external_directory_reference_reader_role" {}
resource "random_uuid" "external_directory_robot_writer_role" {}
resource "random_uuid" "external_directory_enhancement_request_writer_role" {}

# Unique UUIDs for oauth2_permission_scope (delegated permissions)
resource "random_uuid" "external_directory_administrator_scope" {}
resource "random_uuid" "external_directory_importer_scope" {}
resource "random_uuid" "external_directory_reference_reader_scope" {}
resource "random_uuid" "external_directory_robot_writer_scope" {}
resource "random_uuid" "external_directory_enhancement_request_writer_scope" {}

# AD application for destiny repository
# App scopes to allow various functions (i.e. imports) should be added as oauth2_permission_scope here
resource "azuread_application" "external_directory_destiny_repository" {
  provider         = azuread.external_directory
  display_name     = local.name
  sign_in_audience = "AzureADMyOrg"

  api {
    requested_access_token_version = "2"

    oauth2_permission_scope {
      admin_consent_description  = "Allow the app to administer the system as the signed-in user"
      admin_consent_display_name = "Administrator as user"
      id                         = random_uuid.external_directory_administrator_scope.result
      type                       = "User"
      value                      = "administrator.all"
      user_consent_description   = "Allow you to administer the system"
      user_consent_display_name  = "Administrator"
    }

    oauth2_permission_scope {
      admin_consent_description  = "Allow the app to import as the signed-in user"
      admin_consent_display_name = "Import as user"
      id                         = random_uuid.external_directory_importer_scope.result
      type                       = "User"
      value                      = "import.all"
      user_consent_description   = "Allow you to import"
      user_consent_display_name  = "Import"
    }

    oauth2_permission_scope {
      admin_consent_description  = "Allow the app to view references as the signed-in user"
      admin_consent_display_name = "Reference Reader as user"
      id                         = random_uuid.external_directory_reference_reader_scope.result
      type                       = "User"
      value                      = "reference.reader.all"
      user_consent_description   = "Allow you to view references"
      user_consent_display_name  = "Reference Reader"
    }

    oauth2_permission_scope {
      admin_consent_description  = "Allow the app to request enhancements as the signed-in user"
      admin_consent_display_name = "Enhancement Request Writer as user"
      id                         = random_uuid.external_directory_enhancement_request_writer_scope.result
      type                       = "User"
      value                      = "enhancement_request.writer.all"
      user_consent_description   = "Allow you to request enhancements"
      user_consent_display_name  = "Enhancement Request Writer"
    }

    oauth2_permission_scope {
      admin_consent_description  = "Allow the app to register robots and rotate robot client secrets as the signed-in user"
      admin_consent_display_name = "Robot Writer as user"
      id                         = random_uuid.external_directory_robot_writer_scope.result
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

resource "azuread_application_app_role" "external_directory_administrator" {
  provider             = azuread.external_directory
  application_id       = azuread_application.external_directory_destiny_repository.id
  allowed_member_types = ["Application"]
  description          = "Can manage the repository itself"
  display_name         = "Administrator"
  role_id              = random_uuid.external_directory_administrator_role.result
  value                = "administrator"
}

resource "azuread_application_app_role" "external_directory_importer" {
  provider             = azuread.external_directory
  application_id       = azuread_application.external_directory_destiny_repository.id
  allowed_member_types = ["Application"]
  description          = "Importers can import"
  display_name         = "Importers"
  role_id              = random_uuid.external_directory_importer_role.result
  value                = "import.writer"
}

resource "azuread_application_app_role" "external_directory_reference_reader" {
  provider             = azuread.external_directory
  application_id       = azuread_application.external_directory_destiny_repository.id
  allowed_member_types = ["Application"]
  description          = "Can view references"
  display_name         = "Reference Reader"
  role_id              = random_uuid.external_directory_reference_reader_role.result
  value                = "reference.reader"
}

resource "azuread_application_app_role" "external_directory_enhancement_request_writer" {
  provider             = azuread.external_directory
  application_id       = azuread_application.external_directory_destiny_repository.id
  allowed_member_types = ["Application"]
  description          = "Can request enhancements"
  display_name         = "Enhancement Request Writer"
  role_id              = random_uuid.external_directory_enhancement_request_writer_role.result
  value                = "enhancement_request.writer"
}

resource "azuread_service_principal" "external_directory_destiny_repository" {
  provider                     = azuread.external_directory
  client_id                    = azuread_application.external_directory_destiny_repository.client_id
  app_role_assignment_required = false
  owners                       = [data.azuread_client_config.external_directory.object_id]
}

resource "azuread_application_identifier_uri" "external_directory_identifier_uri" {
  provider       = azuread.external_directory
  application_id = azuread_application.external_directory_destiny_repository.id
  identifier_uri = "api://${azuread_application.external_directory_destiny_repository.client_id}"
}

# Grant the GitHub Actions service principal the importer role so it can run the eppi-import GitHub Action
resource "azuread_app_role_assignment" "external_directory_github_actions_to_importer" {
  provider            = azuread.external_directory
  app_role_id         = azuread_application_app_role.external_directory_importer.role_id
  principal_object_id = azuread_service_principal.external_directory_github_actions.object_id
  resource_object_id  = azuread_service_principal.external_directory_destiny_repository.object_id
}

resource "azuread_application_api_access" "external_directory_github_actions" {
  provider       = azuread.external_directory
  application_id = azuread_application_registration.external_directory_github_actions.id
  api_client_id  = azuread_application.external_directory_destiny_repository.client_id

  role_ids = [
    azuread_application_app_role.external_directory_importer.role_id
  ]
}

# Create an application that we can use to authenticate with the Destiny Repository
resource "azuread_application_registration" "external_directory_destiny_repository_auth" {
  provider                       = azuread.external_directory
  display_name                   = "${local.name}-auth-client"
  sign_in_audience               = "AzureADMyOrg"
  requested_access_token_version = 2
}

resource "azuread_application_api_access" "external_directory_destiny_repository_auth" {
  provider       = azuread.external_directory
  application_id = azuread_application_registration.external_directory_destiny_repository_auth.id
  api_client_id  = azuread_application.external_directory_destiny_repository.client_id

  scope_ids = [
    random_uuid.external_directory_administrator_scope.result,
    random_uuid.external_directory_importer_scope.result,
    random_uuid.external_directory_reference_reader_scope.result,
    random_uuid.external_directory_enhancement_request_writer_scope.result,
    random_uuid.external_directory_robot_writer_scope.result,
  ]
}

# This group is managed by click-ops in Entra Id
# Allow group members to authenticate via the auth client
# resource "azuread_app_role_assignment" "external_directory_developer_to_auth" {
#   provider            = azuread.external_directory
#   app_role_id         = "00000000-0000-0000-0000-000000000000"
#   principal_object_id = var.external_directory_developers_group_id
#   resource_object_id  = azuread_service_principal.external_directory_destiny_repository_auth.object_id
# }

resource "azuread_service_principal" "external_directory_destiny_repository_auth" {
  provider                     = azuread.external_directory
  client_id                    = azuread_application_registration.external_directory_destiny_repository_auth.client_id
  app_role_assignment_required = true
  owners                       = [data.azuread_client_config.external_directory.object_id]
}

resource "azuread_application_redirect_uris" "external_directory_local_redirect" {
  # This is necessary to return the token to you if you're grabbing a token for local dev
  provider       = azuread.external_directory
  application_id = azuread_application_registration.external_directory_destiny_repository_auth.id
  type           = "PublicClient"

  redirect_uris = [
    "http://localhost",
    "https://oauth.pstmn.io/v1/callback",
  ]
}

# Openalex incremental updater role assignments
# data "azuread_application" "openalex_incremental_updater" {
#   client_id = var.open_alex_incremental_updater_client_id
# }

# resource "azuread_application_api_access" "openalex_incremental_updater" {
#   application_id = data.azuread_application.openalex_incremental_updater.id
#   api_client_id  = azuread_application.destiny_repository.client_id

#   # Only importer role
#   role_ids = [
#     azuread_application_app_role.importer.role_id
#   ]
# }
