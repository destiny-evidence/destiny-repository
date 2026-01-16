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
