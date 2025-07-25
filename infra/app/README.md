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
- A _unique_ environment name for your deployment, this should be a single word
- Access to the JT_AD Azure tenant

### Create your Terraform Cloud workspace

Create a new workspace in the `destiny-evidence` organisation in TFC with the following name, project, and tag

- Name = "destiny-repository-[YOUR ENVIRONMENT NAME]
- Project = "DESTINY"
- Tag = "destiny-repository"

This will allow TFC to link the terraform defined here to your TFC workspace when you run `terraform init`.

Apply the variable sets for destiny github actions and the JT_AD tenant authentication to your workspace.

Configure all necessary inputs as variables, these are listed in the Terraform Docs below. You can pull the majority of these from other workspaces, but don't forget your unique environment name. Additionally, for temporary workspaces set yourself in the `owner` and `created_by` variables.

Configure your workspace as either a CLI workspace, or as a VCS workspace tied to your branch name.

### The First Apply

You will need to temporarily upgrade the `DESTINY Terraform Cloud` application's access on the JT_AD Tenant to `Cloud Application Administrator` this will allow it to create the resources it requires for setting up Github Actions deployments and Authentication.

Once this is done, you should be able to run a

```sh
terraform apply
```

And create the required resources.

Remove the `Cloud Application Administrator` role from `DESTINY Terraform Cloud` as lower levels of access can read but not change the created resources!

### Deploy out the container app image

Before you can use the deployment of destiny-repository, you will need to deploy out the correct image to the container app. You can use the github action `deploy-to-development.yml` for this. You will need to update it so that the environment has the same name that you've used, push it up, and then run the workflow dispatch.

This will build and deploy out the image from your branch into your container app.

You should be good to go!

### Cleaning up

If you've made a temporary workspace, you'll want to clean it up when you're done.

First, temporarily upgrade the `DESTINY Terraform Cloud` application's access on the JT_AD Tenant to `Cloud Application Administrator` this will allow it to remove the resources.

Push a commit to your VCS branch (or make the changes locally and apply with CLI) removing the lifecycle protection block of your database in `main.tf`.

Then, queue up a destroy

```sh
terraform apply --destroy
```

Once everything is destroyed remove the `Cloud Application Administrator` role from `DESTINY Terraform Cloud` as lower levels of access can read but not change the created resources!

Delete your TFC workspace. You're all done!

### Storage redundancy, backups and recovery process

#### Postgres Flexible Server

The production Postgres Flexible Server is deployed in a Zone-Redundant high availability (HA) configuration. Zone redundant high availability deploys a standby replica in a different zone with automatic failover capability. For more info, see [High availability (Reliability) in Azure Database for PostgreSQL - Flexible Server](https://learn.microsoft.com/en-us/azure/reliability/reliability-postgresql-flexible-server).

Azure Database for PostgreSQL Flexible Server performs regular Zone-redundant backups. We can then do a point-in-time recovery (PITR) within the retention period, currently set to the maximum of 35 days for production and the default of 7 days for non-production.

Performing a PITR creates a new server in the same region as the source server. This can be done via the Azure Portal or via cli. For more info, see [Backup and restore in Azure Database for PostgreSQL flexible server](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/concepts-backup-restore).

If you need to restore a database from a backup, the new server will need to be brought under Terraform management. The recommended way to do this is to use `terraform import`. The high-level steps are:

1. **Restore the database**: Follow the Azure documentation to perform a point-in-time restore. This will create a new PostgreSQL Flexible Server.
2. **Login to Terraform Cloud**: Ensure you are logged into the correct Terraform Cloud organization by running `terraform login`.
3. **Select the correct workspace**: When you run `terraform init`, you will be prompted to select a workspace. Make sure you select the workspace corresponding to the environment you are restoring.
4. **Update Terraform state**: Use `terraform import` to update the state to point to the new server. This command is run locally but will modify the state file in your Terraform Cloud workspace. For more info, see [How to Import Resources into a Remote State Managed by Terraform Cloud](https://support.hashicorp.com/hc/en-us/articles/360061289934-How-to-Import-Resources-into-a-Remote-State-Managed-by-Terraform-Cloud). You will need the Azure resource ID of the new server. You can get this from the "Overview" page of the new server in the Azure Portal and then clicking JSON View. The command will look like: `terraform import azurerm_postgresql_flexible_server.this <new_server_resource_id>`.
5. **Trigger and review plan**: After the import, you need to trigger a new run in Terraform Cloud to apply the consequential changes. You can do this by navigating to your workspace in the Terraform Cloud UI and queuing a new plan. Terraform will detect the new server's FQDN from the imported state and show a plan to update any resources that reference it (e.g., the `DB_CONFIG` environment variable). Review the plan to ensure the changes are expected.
6. **Apply changes**: Apply the changes in the Terraform Cloud UI.
7. **Decommission the old server**: Once you are happy that the application is working with the restored database, you can delete the old server. You can do this from the Azure Portal. You may need to temporarily remove the `prevent_destroy` lifecycle rule from the `azurerm_postgresql_flexible_server_database.this` resource in `main.tf` if you want to delete the old database via Terraform before the import.

#### Storage Account

The storage account uses Locally-Redundant Storage (LRS), which means data is replicated three times within a single data center in the primary region. It does not replicate across availability zones.

As the data is transient, no further backup or recovery processes are in place. If data in the storage account is lost, it will need to be regenerated by re-running the processes that created it.

#### Elasticsearch

The production Elasticsearch cluster is deployed across 3 availability zones, providing high availability. In the event of an issue with a node or an entire availability zone, the cluster will remain available.

Elasticsearch stores snapshots in an off-cluster default repository called found-snapshots. For the production environment, snapshots are taken every 30 minutes. For other environments, they are taken daily. These snapshots are retained for 30 days and can be used to restore the cluster to a specific point in time. For info on how to restore, please see [Restore a snapshot](https://www.elastic.co/docs/deploy-manage/tools/snapshot-and-restore/restore-snapshot).

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
