terraform {
  required_version = ">= 1.0"

  cloud {
    organization = "future-evidence-foundation"

    workspaces {
      project = "destiny"
      tags    = ["destiny-repository"]
    }
  }

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "3.106.1"
    }

    azuread = {
      source  = "hashicorp/azuread"
      version = "3.1.0"
    }

    github = {
      source  = "integrations/github"
      version = "6.6.0"
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
