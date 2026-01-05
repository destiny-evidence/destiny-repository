# Were getting duplicates here with needing the configuration key to exist already.
# Is likely an issue with provider/resource evolution.
data "honeycombio_environment" "this" {
    detail_filter {
      name  = "name"
      value = var.environment
    }
}

resource "honeycombio_api_key" "this" {
  name           = "${var.app_name}-${var.environment}-ingest-api-key"
  environment_id = data.honeycombio_environment.this.id
  type           = "ingest"

  permissions {
    create_datasets = true
  }
}
