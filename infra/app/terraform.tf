terraform {
  required_version = ">= 1.0"

  cloud {
    organization = "destiny-evidence"

    workspaces {
      project = "DESTINY"
      tags    = ["destiny-repository"]
    }
  }

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "4.26.0"
    }

    azuread = {
      source  = "hashicorp/azuread"
      version = "3.1.0"
    }

    azapi = {
      source  = "Azure/azapi"
      version = "2.7.0"
    }

    github = {
      source  = "integrations/github"
      version = "6.6.0"
    }

    ec = {
      source  = "elastic/ec"
      version = "0.12.2"
    }

    elasticstack = {
      source  = "elastic/elasticstack"
      version = "0.11.15"
    }

    honeycombio = {
      source  = "honeycombio/honeycombio"
      version = "0.37.0"
    }
  }
}

provider "azurerm" {
  features {}
}

provider "azuread" {
}

provider "azapi" {
}

provider "github" {
  owner = "destiny-evidence"
  app_auth {
    id              = var.github_app_id
    installation_id = var.github_app_installation_id
    pem_file        = var.github_app_pem
  }
}

provider "ec" {
  apikey = var.elastic_cloud_apikey
}

provider "elasticstack" {
  elasticsearch {
    endpoints = ["${ec_deployment.cluster.elasticsearch.https_endpoint}"]
    username  = ec_deployment.cluster.elasticsearch_username
    password  = ec_deployment.cluster.elasticsearch_password
  }
}

provider "honeycombio" {
  # Honeycomb requires two different API auth scopes

  # v1: configuration
  api_key = var.honeycombio_configuration_api_key

  # v2: provisioning
  api_key_id     = var.honeycombio_api_key_id
  api_key_secret = var.honeycombio_api_key_secret
}
