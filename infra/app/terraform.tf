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
  }
}

provider "azurerm" {
  features {}
}

provider "azuread" {
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
