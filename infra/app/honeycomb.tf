resource "honeycombio_environment" "this" {
  name = var.environment
}


resource "honeycombio_api_key" "this" {
  name           = "${var.app_name}-${var.environment}-ingest-api-key"
  environment_id = honeycombio_environment.this.id
  type           = "ingest"

  permissions {
    create_datasets = true
  }
}
