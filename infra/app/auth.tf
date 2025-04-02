### TODO - create the active directory applications for a) the container app and
# b) for us to authenticate from for the dev environment

# Active directory application for destiny repository
# App roles to allow various functions (i.e. imports) should be defined against this application
resource "azuread_application" "destiny_repository" {
  display_name     = "Destiny Repository ${var.environment}"
  owners           = [data.azuread_client_config.current.object_id]
  sign_in_audience = "AzureADMyOrg"

}

resource "random_uuid" "importer_role" {}

resource "azuread_application_app_role" "importer" {
  application_id = azuread_application.destiny_repository.id
  role_id        = random_uuid.importer_role.id

  allowed_member_types = ["User", "Application"]
  description          = "Importers can import"
  display_name         = "Importers"
  value                = "import"
}

# resource "azuread_service_principal" "destiny_repo" {
#   client_id                    = azuread_application.destiny_repo.client_id
#   app_role_assignment_required = true
# }

# Create a user assigned identity for our client app
resource "azurerm_user_assigned_identity" "my_app" {
  location            = azurerm_resource_group.example.location # Replace the example!
  name                = "my_app"
  resource_group_name = azurerm_resource_group.example.name # Replace the example!
}

# Finally create the role assignment for the client app
resource "azuread_app_role_assignment" "example" {
  app_role_id         = azuread_service_principal.destiny_repo.app_role_ids["import"]
  principal_object_id = azurerm_user_assigned_identity.my_app.principal_id
  resource_object_id  = azuread_service_principal.destiny_repo.object_id
}
