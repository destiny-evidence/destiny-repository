output "api_hostname" {
  description = "Public hostname served by Front Door for the API."
  value       = local.api_hostname
}

output "api_frontdoor_endpoint_host_name" {
  description = "Azure-assigned hostname of the API Front Door endpoint (CNAME target)."
  value       = azurerm_cdn_frontdoor_endpoint.api.host_name
}

output "elasticsearch_password" {
  description = "The password for the elastic user."
  value       = ec_deployment.cluster.elasticsearch_password
  sensitive   = true
}

output "elasticsearch_security_api_key_read_only" {
  description = "The read-only API key for Elasticsearch."
  value       = elasticstack_elasticsearch_security_api_key.read_only.encoded
  sensitive   = true
}
