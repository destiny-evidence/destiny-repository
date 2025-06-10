resource "random_uuid" "importer_role" {}

resource "random_uuid" "reference_reader_role" {}

resource "random_uuid" "reference_writer_role" {}

resource "random_uuid" "robot_writer_role" {}

# App registration for destiny repository
# App roles to allow various functions (i.e. imports) should be added as app role resources here
resource "azuread_application_registration" "destiny_repository" {
  display_name                   = local.name
  sign_in_audience               = "AzureADMyOrg"
  requested_access_token_version = 1
}

resource "azuread_application_app_role" "importer" {
  application_id       = azuread_application_registration.destiny_repository.id
  allowed_member_types = ["User", "Application"]
  description          = "Importers can import"
  display_name         = "Importers"
  role_id              = random_uuid.importer_role.result
  value                = "import"
}

resource "azuread_application_app_role" "reference_reader" {
  application_id       = azuread_application_registration.destiny_repository.id
  allowed_member_types = ["User", "Application"]
  description          = "Can view references"
  display_name         = "Reference Reader"
  role_id              = random_uuid.reference_reader_role.result
  value                = "reference.reader"
}

resource "azuread_application_app_role" "reference_writer" {
  application_id       = azuread_application_registration.destiny_repository.id
  allowed_member_types = ["User", "Application"]
  description          = "Can create and enhance references"
  display_name         = "Reference Writer"
  role_id              = random_uuid.reference_writer_role.result
  value                = "reference.writer"
}

resource "azuread_application_app_role" "robot_writer" {
  application_id       = azuread_application_registration.destiny_repository.id
  allowed_member_types = ["User", "Application"]
  description          = "Can register robots and rotate robot client secrets"
  display_name         = "Robot Writer"
  role_id              = random_uuid.robot_writer_role.result
  value                = "robot.writer"
}

resource "azuread_service_principal" "destiny_repository" {
  client_id                    = azuread_application_registration.destiny_repository.client_id
  app_role_assignment_required = true
  owners                       = [data.azuread_client_config.current.object_id]
}

resource "azuread_application_identifier_uri" "this" {
  application_id = azuread_application_registration.destiny_repository.id
  identifier_uri = "api://${azuread_application_registration.destiny_repository.client_id}"
}

# Assign developers group all authentication scopes
# This group is managed by click-ops in Entra Id
resource "azuread_app_role_assignment" "developer_to_importer" {
  app_role_id         = azuread_application_app_role.importer.role_id
  principal_object_id = var.developers_group_id
  resource_object_id  = azuread_service_principal.destiny_repository.object_id
}

resource "azuread_app_role_assignment" "developer_to_reference_reader" {
  app_role_id         = azuread_application_app_role.reference_reader.role_id
  principal_object_id = var.developers_group_id
  resource_object_id  = azuread_service_principal.destiny_repository.object_id
}

resource "azuread_app_role_assignment" "developer_to_reference_writer" {
  app_role_id         = azuread_application_app_role.reference_writer.role_id
  principal_object_id = var.developers_group_id
  resource_object_id  = azuread_service_principal.destiny_repository.object_id
}

resource "azuread_app_role_assignment" "developer_to_robot_writer" {
  app_role_id         = azuread_application_app_role.robot_writer
  principal_object_id = var.developers_group_id
  resource_object_id  = azuread_service_principal.destiny_repository.object_id
}

# Create an application that we can use to authenticate with the Destiny Repository
resource "azuread_application_registration" "destiny_repository_auth" {
  display_name                   = "${local.name}-auth-client"
  sign_in_audience               = "AzureADMyOrg"
  requested_access_token_version = 1
}

resource "azuread_application_api_access" "destiny_repository_auth" {
  application_id = azuread_application_registration.destiny_repository_auth.id
  api_client_id  = azuread_application_registration.destiny_repository.client_id

  role_ids = [
    azuread_application_app_role.importer.role_id,
    azuread_application_app_role.reference_reader.role_id,
    azuread_application_app_role.reference_writer.role_id,
    azuread_application_app_role.robot_writer.role_id
  ]
}

# This group is managed by click-ops in Entra Id
# Allow group members to authenticate via the auth client
resource "azuread_app_role_assignment" "developer_to_auth" {
  app_role_id         = "00000000-0000-0000-0000-000000000000"
  principal_object_id = var.developers_group_id
  resource_object_id  = azuread_service_principal.destiny_repository_auth.object_id
}

resource "azuread_service_principal" "destiny_repository_auth" {
  client_id                    = azuread_application_registration.destiny_repository_auth.client_id
  app_role_assignment_required = true
  owners                       = [data.azuread_client_config.current.object_id]
}

resource "azuread_application_redirect_uris" "local_redirect" {
  # This is necessary to return the token to you if you're grabbing a token for local dev
  application_id = azuread_application_registration.destiny_repository_auth.id
  type           = "PublicClient"

  redirect_uris = [
    "http://localhost",
    "https://oauth.pstmn.io/v1/callback",
  ]
}

# Openalex incremental updater role assignments
data "azuread_application" "openalex_incremental_updater" {
  client_id = var.open_alex_incremental_updater_client_id
}

resource "azuread_application_api_access" "openalex_incremental_updater" {
  application_id = data.azuread_application.openalex_incremental_updater.id
  api_client_id  = azuread_application_registration.destiny_repository.client_id

  # Only importer role
  role_ids = [
    azuread_application_app_role.importer.role_id
  ]
}
