locals {
  api_hostname = "${var.api_subdomain}.${var.dnsimple_zone_name}"
  ui_hostname  = "${var.ui_subdomain}.${var.dnsimple_zone_name}"
}

data "azurerm_cdn_frontdoor_profile" "shared" {
  name                = var.shared_frontdoor_profile_name
  resource_group_name = var.shared_resource_group_name
}

resource "azurerm_cdn_frontdoor_endpoint" "this" {
  name                     = "fde-${local.name}"
  cdn_frontdoor_profile_id = data.azurerm_cdn_frontdoor_profile.shared.id
  tags                     = local.minimum_resource_tags
}

# --- API ---

resource "azurerm_cdn_frontdoor_origin_group" "api" {
  name                     = "og-api-${local.name}"
  cdn_frontdoor_profile_id = data.azurerm_cdn_frontdoor_profile.shared.id
  session_affinity_enabled = false

  load_balancing {
    additional_latency_in_milliseconds = 50
    sample_size                        = 4
    successful_samples_required        = 3
  }

  health_probe {
    protocol            = "Https"
    interval_in_seconds = 100
    path                = "/v1/system/healthcheck/"
    request_type        = "GET"
  }
}

resource "azurerm_cdn_frontdoor_origin" "api" {
  name                           = "o-api-${local.name}"
  cdn_frontdoor_origin_group_id  = azurerm_cdn_frontdoor_origin_group.api.id
  enabled                        = true
  certificate_name_check_enabled = true
  host_name                      = data.azurerm_container_app.api.ingress[0].fqdn
  origin_host_header             = data.azurerm_container_app.api.ingress[0].fqdn
  http_port                      = 80
  https_port                     = 443
  priority                       = 1
  weight                         = 1000
}

resource "azurerm_cdn_frontdoor_custom_domain" "api" {
  name                     = "cd-api-${local.name}"
  cdn_frontdoor_profile_id = data.azurerm_cdn_frontdoor_profile.shared.id
  host_name                = local.api_hostname

  tls {
    certificate_type = "ManagedCertificate"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "azurerm_cdn_frontdoor_route" "api" {
  name                            = "rt-api-${local.name}"
  cdn_frontdoor_endpoint_id       = azurerm_cdn_frontdoor_endpoint.this.id
  cdn_frontdoor_origin_group_id   = azurerm_cdn_frontdoor_origin_group.api.id
  cdn_frontdoor_origin_ids        = [azurerm_cdn_frontdoor_origin.api.id]
  cdn_frontdoor_custom_domain_ids = [azurerm_cdn_frontdoor_custom_domain.api.id]
  enabled                         = true
  forwarding_protocol             = "HttpsOnly"
  https_redirect_enabled          = true
  patterns_to_match               = ["/*"]
  supported_protocols             = ["Http", "Https"]
  link_to_default_domain          = false
}

resource "dnsimple_zone_record" "api_validation" {
  zone_name = var.dnsimple_zone_name
  name      = "_dnsauth.${var.api_subdomain}"
  type      = "TXT"
  value     = azurerm_cdn_frontdoor_custom_domain.api.validation_token
  ttl       = 3600
}

resource "dnsimple_zone_record" "api" {
  zone_name = var.dnsimple_zone_name
  name      = var.api_subdomain
  type      = "CNAME"
  value     = azurerm_cdn_frontdoor_endpoint.this.host_name
  ttl       = 3600
}

# --- UI ---

resource "azurerm_cdn_frontdoor_origin_group" "ui" {
  name                     = "og-ui-${local.name}"
  cdn_frontdoor_profile_id = data.azurerm_cdn_frontdoor_profile.shared.id
  session_affinity_enabled = false

  load_balancing {
    additional_latency_in_milliseconds = 50
    sample_size                        = 4
    successful_samples_required        = 3
  }
}

resource "azurerm_cdn_frontdoor_origin" "ui" {
  name                           = "o-ui-${local.name}"
  cdn_frontdoor_origin_group_id  = azurerm_cdn_frontdoor_origin_group.ui.id
  enabled                        = true
  certificate_name_check_enabled = true
  host_name                      = data.azurerm_container_app.ui.ingress[0].fqdn
  origin_host_header             = data.azurerm_container_app.ui.ingress[0].fqdn
  http_port                      = 80
  https_port                     = 443
  priority                       = 1
  weight                         = 1000
}

resource "azurerm_cdn_frontdoor_custom_domain" "ui" {
  name                     = "cd-ui-${local.name}"
  cdn_frontdoor_profile_id = data.azurerm_cdn_frontdoor_profile.shared.id
  host_name                = local.ui_hostname

  tls {
    certificate_type = "ManagedCertificate"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "azurerm_cdn_frontdoor_route" "ui" {
  name                            = "rt-ui-${local.name}"
  cdn_frontdoor_endpoint_id       = azurerm_cdn_frontdoor_endpoint.this.id
  cdn_frontdoor_origin_group_id   = azurerm_cdn_frontdoor_origin_group.ui.id
  cdn_frontdoor_origin_ids        = [azurerm_cdn_frontdoor_origin.ui.id]
  cdn_frontdoor_custom_domain_ids = [azurerm_cdn_frontdoor_custom_domain.ui.id]
  enabled                         = true
  forwarding_protocol             = "HttpsOnly"
  https_redirect_enabled          = true
  patterns_to_match               = ["/*"]
  supported_protocols             = ["Http", "Https"]
  link_to_default_domain          = false
}

resource "dnsimple_zone_record" "ui_validation" {
  zone_name = var.dnsimple_zone_name
  name      = "_dnsauth.${var.ui_subdomain}"
  type      = "TXT"
  value     = azurerm_cdn_frontdoor_custom_domain.ui.validation_token
  ttl       = 3600
}

resource "dnsimple_zone_record" "ui" {
  zone_name = var.dnsimple_zone_name
  name      = var.ui_subdomain
  type      = "CNAME"
  value     = azurerm_cdn_frontdoor_endpoint.this.host_name
  ttl       = 3600
}
