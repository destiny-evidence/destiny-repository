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

data "honeycombio_query_specification" "application_errors" {
  calculation {
    op = "COUNT"
  }

  # Note we don't check for any explicit exception fields here, as it allows
  # us to trace context for handled exceptions without alerting for them.
  filter {
    column = "error"
    op     = "exists"
  }

  filter {
    column = "severity"
    op     = "="
    value  = "error"
  }

  filter {
    column = "severity"
    op     = "="
    value  = "critical"
  }

  filter {
    column = "http.status_code"
    op     = ">="
    value  = 500
  }

  filter_combination = "OR"

  time_range = 300
}

resource "honeycombio_query" "application_errors" {
  query_json = data.honeycombio_query_specification.application_errors.json
}

resource "honeycombio_slack_recipient" "alerts" {
  channel = var.honeycomb_alert_slack_channel
}

resource "honeycombio_trigger" "error_trigger" {
  # Free tier only allows two triggers total, so we only create this in production.
  count = var.environment == "production" ? 1 : 0

  name = "Unhandled Exception"

  query_id = honeycombio_query.application_errors.id

  frequency = 300

  alert_type = "on_true"

  threshold {
    op    = ">"
    value = 0
  }

  recipient {
    id = honeycombio_slack_recipient.alerts.id
  }
}
