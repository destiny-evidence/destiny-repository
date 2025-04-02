resource "random_uuid" "importer_role" {}

# App registration for destiny repository
# App roles to allow various functions (i.e. imports) should be added as app role resources here
resource "azuread_application_registration" "destiny_repository" {
  display_name     = "Destiny Repository ${var.environment}"
  sign_in_audience = "AzureADMyOrg"
}

resource "azuread_application_app_role" "importer" {
  application_id       = azuread_application_registration.destiny_repository.id
  allowed_member_types = ["User", "Application"]
  description          = "Importers can import"
  display_name         = "Importers"
  role_id              = random_uuid.importer_role.result
  value                = "import"
}

resource "azuread_service_principal" "destiny_repository" {
  client_id                    = azuread_application_registration.destiny_repository.client_id
  app_role_assignment_required = false
  owners                       = [data.azuread_client_config.current.object_id]
}

resource "azuread_application_identifier_uri" "this" {
  application_id = azuread_application_registration.destiny_repository.id
  identifier_uri = "api://${azuread_application_registration.destiny_repository.client_id}"
}

# Create an application that we can use to authenticate with the Destiny Repository
resource "azuread_application_registration" "destiny_repository_auth" {
  display_name     = "Destiny Repository Auth ${var.environment}"
  sign_in_audience = "AzureADMyOrg"
}

resource "azuread_application_api_access" "destiny_repository_auth" {
  application_id = azuread_application_registration.destiny_repository_auth.id
  api_client_id  = azuread_application_registration.destiny_repository.client_id

  role_ids = [
    azuread_application_app_role.importer.role_id,
  ]

  scope_ids = []
}

resource "azuread_application_redirect_uris" "local_redirect" {
  # This is necessary to return the token to you if you're grabbing a token for local dev
  application_id = azuread_application_registration.destiny_repository_auth.id
  type           = "PublicClient"

  redirect_uris = [
    "http://localhost",
  ]
}

resource "azuread_service_principal" "destiny_repository_auth" {
  client_id                    = azuread_application_registration.destiny_repository_auth.client_id
  app_role_assignment_required = false
  owners                       = [data.azuread_client_config.current.object_id]
}

resource "azuread_app_role_assignment" "importer" {
  app_role_id         = azuread_application_app_role.importer.role_id
  principal_object_id = azuread_service_principal.destiny_repository_auth.object_id
  resource_object_id  = azuread_service_principal.destiny_repository.object_id
}
