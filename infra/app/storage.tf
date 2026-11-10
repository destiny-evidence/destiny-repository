# Static website hosting for the UI, served through Front Door (frontdoor.tf)
resource "azurerm_storage_account" "ui" {
  # Storage account names must be 3-24 chars, lowercase letters and numbers
  # only, and globally unique.
  name                     = "destinyrepoui${substr(var.environment, 0, 4)}"
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  account_kind             = "StorageV2"
  tags                     = local.minimum_resource_tags
}

resource "azurerm_storage_account_static_website" "ui" {
  storage_account_id = azurerm_storage_account.ui.id
  error_404_document = "index.html"
  index_document     = "index.html"
}
