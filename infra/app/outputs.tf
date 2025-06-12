output "elasticsearch_password" {
  value       = ec_deployment.cluster.elasticsearch_password
  sensitive   = true
}
