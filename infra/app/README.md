# Destiny Repository Infrastructure

Infrastructure for deploying the destiny repository infrastructure into an Azure tenant

## Setup

You will need to have access to the `destiny-evidence` terraform cloud (TFC) organisation. Then to run terraform plans, you can do the following

```sh
terraform login
```

Once you're logged in to terraform cloud, you can initialise terraform

```sh
terraform init
```

We identify a set of workspaces that this terraform can be applied to via tagging those workspaces in with `destiny-repository` in TFC. When you initialise terraform, you'll need to select one of those workspaces to plan/apply against.

Each of the workspaces represents a deployment of `destiny-repository` called an environment. If you're developing new infrastructure, you should select `destiny-repository-development` or create your own workspace/environment to work in (see below). You shold be blocked from applying changes to both `staging` and `production` environments by the configuration of their TFC workspaces.

To plan infrastructure changes against a workspace, run

```sh
terraform plan
```

To apply infrastructure changes to a workspace, run

```sh
terraform apply
```

Some infrastructure changes request a higher default set of permissions than we've given terraform. If you hit apply errors you may need to temporarily upgrade the level of access given to Terraform Cloud.

## Creating a new deployment of Destiny Repository

This guide should be followed if you're setting up a new deployment of destiny repository from scratch.

You will need the following

- Access to the `destiny-evidence` TFC organistion
- A _unique_ environment name for your deployment
- Access to the JT_AD Azure tenant

### Create your Terraform Cloud workspace

Create a new worksapce in the `destiny-evidence` organisation in TFC with the following name, project, and tag

- Name = "destiny-repository-[YOUR ENVIRONMENT NAME]
- Project = "DESTINY"
- Tag = "destiny-repository"

This will allow TFC to link the terraform defined here to your TFC workspace when you run `terraform init`.

Apply the variable sets for destiny github actions and the JT_AD tenant authentication to your workspace.

Configure all necessary inputs as variables, these are listed in the Terraform Docs below. You can pull the majority of these from other workspaces, but don't forget your unique environment name. Additionally, for temporary workspaces set yourself in the `owner` and `created_by` variables.

Configure your workspace as either a CLI workspace, or as a VCS workspace tied to your branch name.

### The First Apply

You will need to temporarily upgrade the `DESTINY Terraform Cloud` application's access on the JT_AD Tenant to `Cloud Application Administrator` this will allow it to create the resources it requires for setting up Github Actions deployments and Authentication.

Additionally, one of the resources created is a init container for destiny repository that runs database migrations. Unfortunately it isn't possible to change the image tag on an init container, so you will need to pre-seed the container registry with an appropriately tagged image for the init container (deployments from github will handle updating the tag from here on our). From the _root_ directory of this repo, run

```sh
az acr login --name destinyevidenceregistry
docker buildx build --platform linux/amd64 -t  destinyevidenceregistry.azurecr.io/destiny-repository:[YOUR ENVIRONMENT NAME] .
docker push destinyevidenceregistry.azurecr.io/destiny-repository:[YOUR ENVIRONMENT NAME]
```

Once this is done, you should be able to run a

```sh
terraform apply
```

And create the required resources.

Remove the `Cloud Application Administrator` role from `DESTINY Terraform Cloud` as lower levels of access can read but not change the created resources!

### Deploy out the container app image

Before you can use the deployment of destiny-repository, you will need to deploy out the correct image to the container app. You can use the github ac

### Generating Terraform Docs

Docs generated with [terraform-docs](github.com/terraform-docs/terraform-docs). Run the following from this directory.

```sh
terraform-docs markdown --output-file README.md .
```

<!-- BEGIN_TF_DOCS -->

## Requirements

| Name                                                                     | Version |
| ------------------------------------------------------------------------ | ------- |
| <a name="requirement_terraform"></a> [terraform](#requirement_terraform) | >= 1.0  |
| <a name="requirement_azuread"></a> [azuread](#requirement_azuread)       | 3.1.0   |
| <a name="requirement_azurerm"></a> [azurerm](#requirement_azurerm)       | 4.26.0  |
| <a name="requirement_github"></a> [github](#requirement_github)          | 6.6.0   |

## Providers

| Name                                                         | Version |
| ------------------------------------------------------------ | ------- |
| <a name="provider_azuread"></a> [azuread](#provider_azuread) | 3.1.0   |
| <a name="provider_azurerm"></a> [azurerm](#provider_azurerm) | 4.26.0  |
| <a name="provider_github"></a> [github](#provider_github)    | 6.6.0   |
| <a name="provider_random"></a> [random](#provider_random)    | 3.7.1   |

## Modules

| Name                                                                                         | Source                                                          | Version |
| -------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ------- |
| <a name="module_container_app"></a> [container_app](#module_container_app)                   | app.terraform.io/future-evidence-foundation/container-app/azure | 1.3.0   |
| <a name="module_container_app_tasks"></a> [container_app_tasks](#module_container_app_tasks) | app.terraform.io/future-evidence-foundation/container-app/azure | 1.3.0   |

## Resources

| Name                                                                                                                                                                                 | Type        |
| ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------- |
| [azuread_app_role_assignment.developer_to_auth](https://registry.terraform.io/providers/hashicorp/azuread/3.1.0/docs/resources/app_role_assignment)                                  | resource    |
| [azuread_app_role_assignment.developer_to_importer](https://registry.terraform.io/providers/hashicorp/azuread/3.1.0/docs/resources/app_role_assignment)                              | resource    |
| [azuread_application_api_access.destiny_repository_auth](https://registry.terraform.io/providers/hashicorp/azuread/3.1.0/docs/resources/application_api_access)                      | resource    |
| [azuread_application_app_role.importer](https://registry.terraform.io/providers/hashicorp/azuread/3.1.0/docs/resources/application_app_role)                                         | resource    |
| [azuread_application_federated_identity_credential.github](https://registry.terraform.io/providers/hashicorp/azuread/3.1.0/docs/resources/application_federated_identity_credential) | resource    |
| [azuread_application_identifier_uri.this](https://registry.terraform.io/providers/hashicorp/azuread/3.1.0/docs/resources/application_identifier_uri)                                 | resource    |
| [azuread_application_redirect_uris.local_redirect](https://registry.terraform.io/providers/hashicorp/azuread/3.1.0/docs/resources/application_redirect_uris)                         | resource    |
| [azuread_application_registration.destiny_repository](https://registry.terraform.io/providers/hashicorp/azuread/3.1.0/docs/resources/application_registration)                       | resource    |
| [azuread_application_registration.destiny_repository_auth](https://registry.terraform.io/providers/hashicorp/azuread/3.1.0/docs/resources/application_registration)                  | resource    |
| [azuread_application_registration.github_actions](https://registry.terraform.io/providers/hashicorp/azuread/3.1.0/docs/resources/application_registration)                           | resource    |
| [azuread_service_principal.destiny_repository](https://registry.terraform.io/providers/hashicorp/azuread/3.1.0/docs/resources/service_principal)                                     | resource    |
| [azuread_service_principal.destiny_repository_auth](https://registry.terraform.io/providers/hashicorp/azuread/3.1.0/docs/resources/service_principal)                                | resource    |
| [azuread_service_principal.github_actions](https://registry.terraform.io/providers/hashicorp/azuread/3.1.0/docs/resources/service_principal)                                         | resource    |
| [azurerm_network_security_group.db](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/network_security_group)                                          | resource    |
| [azurerm_postgresql_flexible_server.this](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/postgresql_flexible_server)                                | resource    |
| [azurerm_postgresql_flexible_server_database.this](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/postgresql_flexible_server_database)              | resource    |
| [azurerm_private_dns_zone.db](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/private_dns_zone)                                                      | resource    |
| [azurerm_private_dns_zone_virtual_network_link.db](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/private_dns_zone_virtual_network_link)            | resource    |
| [azurerm_resource_group.this](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/resource_group)                                                        | resource    |
| [azurerm_role_assignment.container-app-queue-contributor](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/role_assignment)                           | resource    |
| [azurerm_role_assignment.container-app-tasks-queue-contributor](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/role_assignment)                     | resource    |
| [azurerm_role_assignment.gha-container-app-contributor](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/role_assignment)                             | resource    |
| [azurerm_role_assignment.gha-container-app-env-contributor](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/role_assignment)                         | resource    |
| [azurerm_role_assignment.gha-container-app-tasks-contributor](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/role_assignment)                       | resource    |
| [azurerm_role_assignment.gha-container-pull](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/role_assignment)                                        | resource    |
| [azurerm_role_assignment.gha-container-push](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/role_assignment)                                        | resource    |
| [azurerm_servicebus_namespace.this](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/servicebus_namespace)                                            | resource    |
| [azurerm_servicebus_namespace_authorization_rule.this](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/servicebus_namespace_authorization_rule)      | resource    |
| [azurerm_servicebus_queue.taskiq](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/servicebus_queue)                                                  | resource    |
| [azurerm_storage_account.this](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/storage_account)                                                      | resource    |
| [azurerm_subnet.app](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/subnet)                                                                         | resource    |
| [azurerm_subnet.db](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/subnet)                                                                          | resource    |
| [azurerm_subnet.tasks](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/subnet)                                                                       | resource    |
| [azurerm_subnet_network_security_group_association.db](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/subnet_network_security_group_association)    | resource    |
| [azurerm_user_assigned_identity.container_apps_identity](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/user_assigned_identity)                     | resource    |
| [azurerm_user_assigned_identity.container_apps_tasks_identity](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/user_assigned_identity)               | resource    |
| [azurerm_virtual_network.this](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/resources/virtual_network)                                                      | resource    |
| [github_actions_environment_variable.app_name](https://registry.terraform.io/providers/integrations/github/6.6.0/docs/resources/actions_environment_variable)                        | resource    |
| [github_actions_environment_variable.azure_client_id](https://registry.terraform.io/providers/integrations/github/6.6.0/docs/resources/actions_environment_variable)                 | resource    |
| [github_actions_environment_variable.azure_subscription_id](https://registry.terraform.io/providers/integrations/github/6.6.0/docs/resources/actions_environment_variable)           | resource    |
| [github_actions_environment_variable.azure_tenant_id](https://registry.terraform.io/providers/integrations/github/6.6.0/docs/resources/actions_environment_variable)                 | resource    |
| [github_actions_environment_variable.container_app_env](https://registry.terraform.io/providers/integrations/github/6.6.0/docs/resources/actions_environment_variable)               | resource    |
| [github_actions_environment_variable.container_app_name](https://registry.terraform.io/providers/integrations/github/6.6.0/docs/resources/actions_environment_variable)              | resource    |
| [github_actions_environment_variable.container_app_tasks_name](https://registry.terraform.io/providers/integrations/github/6.6.0/docs/resources/actions_environment_variable)        | resource    |
| [github_actions_environment_variable.container_registry_name](https://registry.terraform.io/providers/integrations/github/6.6.0/docs/resources/actions_environment_variable)         | resource    |
| [github_actions_environment_variable.github_environment_name](https://registry.terraform.io/providers/integrations/github/6.6.0/docs/resources/actions_environment_variable)         | resource    |
| [github_actions_environment_variable.resource_group](https://registry.terraform.io/providers/integrations/github/6.6.0/docs/resources/actions_environment_variable)                  | resource    |
| [github_repository_environment.environment](https://registry.terraform.io/providers/integrations/github/6.6.0/docs/resources/repository_environment)                                 | resource    |
| [random_uuid.importer_role](https://registry.terraform.io/providers/hashicorp/random/latest/docs/resources/uuid)                                                                     | resource    |
| [azuread_client_config.current](https://registry.terraform.io/providers/hashicorp/azuread/3.1.0/docs/data-sources/client_config)                                                     | data source |
| [azurerm_container_registry.this](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/data-sources/container_registry)                                             | data source |
| [azurerm_subscription.current](https://registry.terraform.io/providers/hashicorp/azurerm/4.26.0/docs/data-sources/subscription)                                                      | data source |

## Inputs

| Name                                                                                                                                 | Description                                                                                          | Type     | Default                                 | Required |
| ------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------- | -------- | --------------------------------------- | :------: |
| <a name="input_admin_login"></a> [admin_login](#input_admin_login)                                                                   | admin login for the app database                                                                     | `string` | n/a                                     |   yes    |
| <a name="input_admin_password"></a> [admin_password](#input_admin_password)                                                          | admin password for the app database                                                                  | `string` | n/a                                     |   yes    |
| <a name="input_app_max_replicas"></a> [app_max_replicas](#input_app_max_replicas)                                                    | Maximum number of replicas for the app container app                                                 | `number` | `10`                                    |    no    |
| <a name="input_app_name"></a> [app_name](#input_app_name)                                                                            | Application Name                                                                                     | `string` | `"destiny-repository"`                  |    no    |
| <a name="input_azure_tenant_id"></a> [azure_tenant_id](#input_azure_tenant_id)                                                       | ID of the azure application                                                                          | `string` | n/a                                     |   yes    |
| <a name="input_budget_code"></a> [budget_code](#input_budget_code)                                                                   | Budget code for tagging resource groups. Required tag for resource groups                            | `string` | n/a                                     |   yes    |
| <a name="input_container_registry_name"></a> [container_registry_name](#input_container_registry_name)                               | The name of the container registry being used                                                        | `string` | n/a                                     |   yes    |
| <a name="input_container_registry_resource_group"></a> [container_registry_resource_group](#input_container_registry_resource_group) | The name of the resource group the container registry is in                                          | `string` | n/a                                     |   yes    |
| <a name="input_cpu_scaling_threshold"></a> [cpu_scaling_threshold](#input_cpu_scaling_threshold)                                     | CPU threshold for scaling the app container app                                                      | `number` | `70`                                    |    no    |
| <a name="input_created_by"></a> [created_by](#input_created_by)                                                                      | Who created this infrastrcuture. Required tag for resource groups                                    | `string` | n/a                                     |   yes    |
| <a name="input_developers_group_id"></a> [developers_group_id](#input_developers_group_id)                                           | Id of a group to assign to all API roles on destiny repository, allowing api authentication for devs | `string` | n/a                                     |   yes    |
| <a name="input_environment"></a> [environment](#input_environment)                                                                   | The name of the environment this stack is being deployed to                                          | `string` | n/a                                     |   yes    |
| <a name="input_github_app_id"></a> [github_app_id](#input_github_app_id)                                                             | The app id for GitHub app used to configure github                                                   | `string` | n/a                                     |   yes    |
| <a name="input_github_app_installation_id"></a> [github_app_installation_id](#input_github_app_installation_id)                      | The app installation ID for the GitHub App used to configure github                                  | `string` | n/a                                     |   yes    |
| <a name="input_github_app_pem"></a> [github_app_pem](#input_github_app_pem)                                                          | The app pem file for authenticating as a GitHub App                                                  | `string` | n/a                                     |   yes    |
| <a name="input_github_repo"></a> [github_repo](#input_github_repo)                                                                   | GitHub repo to use for GitHub Actions                                                                | `string` | `"destiny-evidence/destiny-repository"` |    no    |
| <a name="input_owner"></a> [owner](#input_owner)                                                                                     | Email of the owner of this infrastructure. Required tag for resource groups                          | `string` | n/a                                     |   yes    |
| <a name="input_project"></a> [project](#input_project)                                                                               | Email of the owner of this infrastructure. Required tag for resource groups                          | `string` | n/a                                     |   yes    |
| <a name="input_queue_length_scaling_threshold"></a> [queue_length_scaling_threshold](#input_queue_length_scaling_threshold)          | Queue length threshold for scaling the tasks container app                                           | `number` | `100`                                   |    no    |
| <a name="input_region"></a> [region](#input_region)                                                                                  | The region resources will be deployed into                                                           | `string` | n/a                                     |   yes    |
| <a name="input_tasks_max_replicas"></a> [tasks_max_replicas](#input_tasks_max_replicas)                                              | Maximum number of replicas for the tasks container app                                               | `number` | `10`                                    |    no    |

## Outputs

No outputs.

<!-- END_TF_DOCS -->
