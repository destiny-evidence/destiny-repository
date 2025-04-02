resource "random_uuid" "importer_role" {}

# Active directory application for destiny repository
# App roles to allow various functions (i.e. imports) should be added as app role resources here
resource "azuread_application" "destiny_repository" {
  display_name     = "Destiny Repository ${var.environment}"
  owners           = [data.azuread_client_config.current.object_id]
  sign_in_audience = "AzureADMyOrg"

  app_role {
    allowed_member_types = ["User", "Application"]
    description          = "Importers can import"
    display_name         = "Importers"
    id                   = random_uuid.importer_role.id
    value                = "import"
    enabled              = true
  }

  lifecycle {
    ignore_changes = [
      identifier_uris,
    ]
  }
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

# Create an application that we can use to authenticate with the Destiny Repository
resource "azuread_application" "destiny_repository_auth" {
  display_name     = "Destiny Repository Auth ${var.environment}"
  owners           = [data.azuread_client_config.current.object_id]
  sign_in_audience = "AzureADMyOrg"

  required_resource_access {
    resource_app_id = azuread_application.destiny_repository.client_id

    resource_access {
      id   = azuread_service_principal.destiny_repository.app_role_ids["import"]
      type = "Role"
    }
  }
}

resource "azuread_application_redirect_uris" "local_redirect" {
  application_id = azuread_application.destiny_repository_auth.id
  type           = "PublicClient"

  redirect_uris = [
    "http://localhost",
  ]
}

resource "azuread_service_principal" "destiny_repository_auth" {
  client_id                    = azuread_application.destiny_repository_auth.client_id
  app_role_assignment_required = false
  owners                       = [data.azuread_client_config.current.object_id]
}

resource "azuread_app_role_assignment" "importer" {
  app_role_id         = azuread_application.destiny_repository.app_role_ids["import"]
  principal_object_id = azuread_service_principal.destiny_repository_auth.object_id
  resource_object_id  = azuread_service_principal.destiny_repository.object_id
}
