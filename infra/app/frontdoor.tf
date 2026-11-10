locals {
  api_hostname = "${var.api_subdomain}.${var.dnsimple_zone_name}"
  ui_hostname  = "${var.ui_subdomain}.${var.dnsimple_zone_name}"

  # Only the attributes both endpoint types share, so the conditional types match
  frontdoor_endpoint = local.is_production ? {
    id        = azurerm_cdn_frontdoor_endpoint.this[0].id
    name      = azurerm_cdn_frontdoor_endpoint.this[0].name
    host_name = azurerm_cdn_frontdoor_endpoint.this[0].host_name
    } : {
    id        = data.azurerm_cdn_frontdoor_endpoint.shared[0].id
    name      = data.azurerm_cdn_frontdoor_endpoint.shared[0].name
    host_name = data.azurerm_cdn_frontdoor_endpoint.shared[0].host_name
  }
}

data "azurerm_cdn_frontdoor_profile" "shared" {
  name                = var.shared_frontdoor_profile_name
  resource_group_name = var.shared_resource_group_name
}

data "azurerm_cdn_frontdoor_endpoint" "shared" {
  count               = local.is_production ? 0 : 1
  name                = "fde-${var.environment}"
  profile_name        = var.shared_frontdoor_profile_name
  resource_group_name = var.shared_resource_group_name
}

resource "azurerm_cdn_frontdoor_endpoint" "this" {
  count                    = local.is_production ? 1 : 0
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
    path                = "/v1/system/ping/"
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
  name                     = replace(local.api_hostname, ".", "-")
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
  cdn_frontdoor_endpoint_id       = local.frontdoor_endpoint.id
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


resource "azurerm_cdn_frontdoor_custom_domain_association" "api" {
  cdn_frontdoor_custom_domain_id = azurerm_cdn_frontdoor_custom_domain.api.id
  cdn_frontdoor_route_ids        = [azurerm_cdn_frontdoor_route.api.id]
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
  value     = local.frontdoor_endpoint.host_name
  ttl       = 3600
}

# --- UI ---
# A static bundle served from blob storage; see storage.tf.

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
  host_name                      = azurerm_storage_account.ui.primary_web_host
  origin_host_header             = azurerm_storage_account.ui.primary_web_host
  http_port                      = 80
  https_port                     = 443
  priority                       = 1
  weight                         = 1000
}

resource "azurerm_cdn_frontdoor_custom_domain" "ui" {
  name                     = replace(local.ui_hostname, ".", "-")
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
  cdn_frontdoor_endpoint_id       = local.frontdoor_endpoint.id
  cdn_frontdoor_origin_group_id   = azurerm_cdn_frontdoor_origin_group.ui.id
  cdn_frontdoor_origin_ids        = [azurerm_cdn_frontdoor_origin.ui.id]
  cdn_frontdoor_custom_domain_ids = [azurerm_cdn_frontdoor_custom_domain.ui.id]
  cdn_frontdoor_rule_set_ids      = [azurerm_cdn_frontdoor_rule_set.ui_cache.id]
  enabled                         = true
  forwarding_protocol             = "HttpsOnly"
  https_redirect_enabled          = true
  patterns_to_match               = ["/*"]
  supported_protocols             = ["Http", "Https"]
  link_to_default_domain          = false

  cache {
    query_string_caching_behavior = "UseQueryString"
    compression_enabled           = true
    content_types_to_compress     = ["text/html", "application/javascript", "text/css", "application/json"]
  }
}

# Cache rules: hashed assets cached aggressively, HTML revalidates every time
resource "azurerm_cdn_frontdoor_rule_set" "ui_cache" {
  name                     = "cacheui${replace(local.name, "-", "")}"
  cdn_frontdoor_profile_id = data.azurerm_cdn_frontdoor_profile.shared.id
}

# Hashed static assets (JS, CSS, fonts, images): long-lived cache
resource "azurerm_cdn_frontdoor_rule" "ui_cache_assets" {
  name                      = "CacheAssets"
  cdn_frontdoor_rule_set_id = azurerm_cdn_frontdoor_rule_set.ui_cache.id
  order                     = 1
  behavior_on_match         = "Stop"

  conditions {
    url_file_extension_condition {
      operator     = "Equal"
      match_values = ["js", "css", "woff", "woff2", "png", "jpg", "svg", "ico"]
    }
  }

  actions {
    route_configuration_override_action {
      cache_behavior                = "OverrideAlways"
      cache_duration                = "30.00:00:00"
      compression_enabled           = true
      query_string_caching_behavior = "UseQueryString"
    }
    response_header_action {
      header_action = "Overwrite"
      header_name   = "Cache-Control"
      value         = "public, max-age=2592000, immutable"
    }
  }
}

# HTML files: browser revalidates with Front Door each time
resource "azurerm_cdn_frontdoor_rule" "ui_html_no_cache" {
  name                      = "HtmlNoCache"
  cdn_frontdoor_rule_set_id = azurerm_cdn_frontdoor_rule_set.ui_cache.id
  order                     = 2
  behavior_on_match         = "Stop"

  conditions {
    url_file_extension_condition {
      operator     = "Equal"
      match_values = ["html"]
    }
  }

  actions {
    response_header_action {
      header_action = "Overwrite"
      header_name   = "Cache-Control"
      value         = "no-cache"
    }
  }
}

# SPA fallback: rewrite extensionless paths to /index.html so the origin
# returns 200 instead of 404 (blob storage error_404_document preserves the
# 404 status code, which breaks client-side routing).
resource "azurerm_cdn_frontdoor_rule" "ui_spa_rewrite" {
  name                      = "SpaRewrite"
  cdn_frontdoor_rule_set_id = azurerm_cdn_frontdoor_rule_set.ui_cache.id
  order                     = 3
  behavior_on_match         = "Continue"

  conditions {
    url_file_extension_condition {
      operator         = "LessThan"
      match_values     = ["1"]
      negate_condition = false
    }
  }

  actions {
    url_rewrite_action {
      source_pattern          = "/"
      destination             = "/index.html"
      preserve_unmatched_path = false
    }
    response_header_action {
      header_action = "Overwrite"
      header_name   = "Cache-Control"
      value         = "no-cache"
    }
  }
}

# Catch-all: everything not matched above revalidates on every request
resource "azurerm_cdn_frontdoor_rule" "ui_default_no_cache" {
  name                      = "DefaultNoCache"
  cdn_frontdoor_rule_set_id = azurerm_cdn_frontdoor_rule_set.ui_cache.id
  order                     = 4

  actions {
    response_header_action {
      header_action = "Overwrite"
      header_name   = "Cache-Control"
      value         = "no-cache"
    }
  }
}

resource "azurerm_cdn_frontdoor_custom_domain_association" "ui" {
  cdn_frontdoor_custom_domain_id = azurerm_cdn_frontdoor_custom_domain.ui.id
  cdn_frontdoor_route_ids        = [azurerm_cdn_frontdoor_route.ui.id]
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
  value     = local.frontdoor_endpoint.host_name
  ttl       = 3600
}
