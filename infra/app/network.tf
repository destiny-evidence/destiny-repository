resource "azurerm_virtual_network" "this" {
  name                = "vnet-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  address_space       = ["10.0.0.0/16"]

  tags = local.minimum_resource_tags
}

resource "azurerm_network_security_group" "db" {
  name                = "nsg-${local.name}-db"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  tags = local.minimum_resource_tags
}

resource "azurerm_network_security_rule" "allow_vpn_to_postgres" {
  name                        = "AllowVpnToPostgres"
  priority                    = 100
  direction                   = "Inbound"
  access                      = "Allow"
  protocol                    = "Tcp"
  source_port_range           = "*"
  destination_port_range      = "5432"
  source_address_prefix       = "172.16.0.0/24" # VPN Client Address Pool
  destination_address_prefix  = azurerm_subnet.db.address_prefixes[0]
  resource_group_name         = azurerm_resource_group.this.name
  network_security_group_name = azurerm_network_security_group.db.name
}

resource "azurerm_subnet" "db" {
  name                 = "sn-${local.name}-db"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.0.2.0/24"]

  delegation {
    name = "fs"
    service_delegation {
      name = "Microsoft.DBforPostgreSQL/flexibleServers"
      actions = [
        "Microsoft.Network/virtualNetworks/subnets/join/action",
      ]
    }
  }
}

resource "azurerm_subnet_network_security_group_association" "db" {
  subnet_id                 = azurerm_subnet.db.id
  network_security_group_id = azurerm_network_security_group.db.id
}

resource "azurerm_private_dns_zone" "db" {
  name                = "${local.name}.postgres.database.azure.com"
  resource_group_name = azurerm_resource_group.this.name
}

resource "azurerm_private_dns_zone_virtual_network_link" "db" {
  name                  = "${local.name}-vnl"
  private_dns_zone_name = azurerm_private_dns_zone.db.name
  virtual_network_id    = azurerm_virtual_network.this.id
  resource_group_name   = azurerm_resource_group.this.name
  depends_on            = [azurerm_subnet.db, azurerm_subnet.app, azurerm_subnet.tasks, azurerm_subnet.gateway]
}

resource "azurerm_subnet" "app" {
  name                 = "sn-${local.name}-app"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.0.4.0/23"]
}

resource "azurerm_subnet" "tasks" {
  name                 = "sn-${local.name}-tasks"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.0.6.0/23"]
}

resource "azurerm_subnet" "gateway" {
  name                 = "GatewaySubnet"
  resource_group_name  = azurerm_resource_group.this.name
  virtual_network_name = azurerm_virtual_network.this.name
  address_prefixes     = ["10.0.8.0/24"]
}

resource "azurerm_public_ip" "vpn_gateway" {
  name                = "pip-vpngw-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  allocation_method   = "Static"
  sku                 = "Standard"
  tags                = local.minimum_resource_tags
}

resource "azurerm_virtual_network_gateway" "vpn_gateway" {
  name                = "vpngw-${local.name}"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name

  type     = "Vpn"
  vpn_type = "RouteBased"
  sku      = "VpnGw1" # Lowest SKU

  active_active = false
  enable_bgp    = false

  ip_configuration {
    name                          = "vpngw-ipconfig"
    public_ip_address_id          = azurerm_public_ip.vpn_gateway.id
    private_ip_address_allocation = "Dynamic"
    subnet_id                     = azurerm_subnet.gateway.id
  }

  vpn_client_configuration {
    address_space = ["172.16.0.0/24"] # Address pool for VPN clients

    vpn_client_protocols = ["OpenVPN"]
    aad_tenant           = "https://login.microsoftonline.com/${var.azure_tenant_id}/"
    aad_audience         = "41b23e61-6c1e-4545-b367-cd054e0ed4b4" # https://learn.microsoft.com/en-us/azure/vpn-gateway/openvpn-azure-ad-tenant
    aad_issuer           = "https://sts.windows.net/${var.azure_tenant_id}/"
  }

  tags = local.minimum_resource_tags

  depends_on = [azurerm_public_ip.vpn_gateway, azurerm_subnet.gateway]
}

resource "azurerm_role_assignment" "vpn_gateway_developers_access" {
  scope                = azurerm_virtual_network_gateway.vpn_gateway.id
  role_definition_name = "VPN Users"
  principal_id         = var.developers_group_id
}
