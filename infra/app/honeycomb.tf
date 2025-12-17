resource "honeycombio_environment" "this" {
  name = var.environment
}

resource "honeycombio_environment" "github_actions" {
  name = "github-actions"
}


resource "honeycombio_api_key" "this" {
  name           = "${var.app_name}-${var.environment}-ingest-api-key"
  environment_id = honeycombio_environment.this.id
  type           = "ingest"

  permissions {
    create_datasets = true
  }
}


resource "honeycombio_api_key" "github_actions" {
  name           = "${var.app_name}-github-actions-ingest-api-key"
  environment_id = honeycombio_environment.github_actions.id
  type           = "ingest"

  permissions {
    create_datasets = true
  }
}
