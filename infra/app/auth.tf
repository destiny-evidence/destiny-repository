# Unique UUIDs for app roles (application permissions)
resource "random_uuid" "administrator_role" {}
resource "random_uuid" "importer_role" {}
resource "random_uuid" "reference_reader_role" {}
resource "random_uuid" "reference_full_text_reader_role" {}
resource "random_uuid" "reference_deduplicator_role" {}
resource "random_uuid" "robot_writer_role" {}
resource "random_uuid" "robot_entitlement_writer_role" {}
resource "random_uuid" "enhancement_request_writer_role" {}

# AD application via managed identities for destiny repository.
resource "azuread_application" "destiny_repository" {
  display_name     = local.name
  sign_in_audience = "AzureADMyOrg"

  api {
    requested_access_token_version = 2
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

resource "azuread_application_app_role" "reference_full_text_reader" {
  application_id       = azuread_application.destiny_repository.id
  allowed_member_types = ["Application"]
  description          = "Can view the full texts of references"
  display_name         = "Reference Full Text Reader"
  role_id              = random_uuid.reference_full_text_reader_role.result
  value                = "reference.full_text.reader"
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

resource "azuread_application_app_role" "robot_writer" {
  application_id       = azuread_application.destiny_repository.id
  allowed_member_types = ["Application"]
  description          = "Can register robots and rotate robot client secrets"
  display_name         = "Robot Writer"
  role_id              = random_uuid.robot_writer_role.result
  value                = "robot.writer"
}

resource "azuread_application_app_role" "robot_entitlement_writer" {
  application_id       = azuread_application.destiny_repository.id
  allowed_member_types = ["Application"]
  description          = "Can write entitlements on robots"
  display_name         = "Robot Entitlement Writer"
  role_id              = random_uuid.robot_entitlement_writer_role.result
  value                = "robot.entitlement.writer"
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
data "azurerm_user_assigned_identity" "destiny_demonstrator_ui" {
  count               = var.environment == "development" ? 0 : 1
  name                = var.destiny_demonstrator_ui_app_name
  resource_group_name = "rg-${var.destiny_demonstrator_ui_app_name}-${var.environment}"
}

resource "azuread_app_role_assignment" "destiny_demonstrator_ui_to_reference_reader" {
  count               = var.environment == "development" ? 0 : 1
  app_role_id         = azuread_application_app_role.reference_reader.role_id
  principal_object_id = data.azurerm_user_assigned_identity.destiny_demonstrator_ui[0].principal_id
  resource_object_id  = azuread_service_principal.destiny_repository.object_id
}

# AI Evidence Summariser role assignments
data "azurerm_user_assigned_identity" "ai_evidence_summariser" {
  count               = var.environment != "development" && var.ai_evidence_summariser_app_name != null ? 1 : 0
  name                = "${var.ai_evidence_summariser_app_name}-${var.environment}"
  resource_group_name = "rg-${var.ai_evidence_summariser_app_name}-${var.environment}"
}

resource "azuread_app_role_assignment" "ai_evidence_summariser_to_reference_reader" {
  count               = length(data.azurerm_user_assigned_identity.ai_evidence_summariser)
  app_role_id         = azuread_application_app_role.reference_reader.role_id
  principal_object_id = data.azurerm_user_assigned_identity.ai_evidence_summariser[0].principal_id
  resource_object_id  = azuread_service_principal.destiny_repository.object_id
}

resource "azuread_app_role_assignment" "ai_evidence_summariser_to_reference_full_text_reader" {
  count               = length(data.azurerm_user_assigned_identity.ai_evidence_summariser)
  app_role_id         = azuread_application_app_role.reference_full_text_reader.role_id
  principal_object_id = data.azurerm_user_assigned_identity.ai_evidence_summariser[0].principal_id
  resource_object_id  = azuread_service_principal.destiny_repository.object_id
}
