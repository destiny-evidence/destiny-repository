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
  }
}

provider "azurerm" {
  features {}
}
