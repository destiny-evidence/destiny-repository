locals {
  api_hostname = "${var.api_subdomain}.${var.dnsimple_zone_name}"
}

data "azurerm_cdn_frontdoor_profile" "shared" {
  name                = var.shared_frontdoor_profile_name
  resource_group_name = var.shared_resource_group_name
}

resource "azurerm_cdn_frontdoor_endpoint" "api" {
  name                     = "api-${var.environment}"
  cdn_frontdoor_profile_id = data.azurerm_cdn_frontdoor_profile.shared.id
  tags                     = local.minimum_resource_tags
}

resource "azurerm_cdn_frontdoor_origin_group" "api" {
  name                     = "api-${var.environment}"
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
  name                           = "api-${var.environment}"
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
  name                     = "api-${var.environment}"
  cdn_frontdoor_profile_id = data.azurerm_cdn_frontdoor_profile.shared.id
  host_name                = local.api_hostname

  tls {
    certificate_type = "ManagedCertificate"
  }
}

resource "azurerm_cdn_frontdoor_route" "api" {
  name                            = "api-${var.environment}"
  cdn_frontdoor_endpoint_id       = azurerm_cdn_frontdoor_endpoint.api.id
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

# Front Door validates ownership of the custom domain by checking a TXT record
# at `_dnsauth.<subdomain>`. The CNAME is what actually routes traffic.
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
  value     = azurerm_cdn_frontdoor_endpoint.api.host_name
  ttl       = 3600
}
