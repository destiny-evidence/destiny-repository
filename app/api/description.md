### Changelog

Here is a summative changelog of each major version. In general only major breaking changes are listed here, additive and backward-compatible changes can and will be made continuously.

#### V1

Key focus: standardisation and sanitation. These are overwhelmingly URL schema changes, not functional changes.

| Old Endpoint                                             | New Endpoint                                                      | Other Changes                                                       |
| -------------------------------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------- |
| `POST /imports/record/`                                  | `POST /v1/imports/records/`                                       | -                                                                   |
| `GET /imports/record/{record_id}/`                       | `GET /v1/imports/records/{record_id}/`                            | -                                                                   |
| `PATCH /imports/record/{record_id}/finalise/`            | `PATCH /v1/imports/records/{record_id}/finalise/`                 | -                                                                   |
| `POST /imports/record/{record_id}/batch/`                | `POST /v1/imports/records/{record_id}/batches/`                   | -                                                                   |
| `GET /imports/record/{record_id}/batch/`                 | `GET /v1/imports/records/{record_id}/batches/`                    | -                                                                   |
| `GET /imports/batch/{batch_id}/`                         | `GET /v1/imports/records/{record_id}/batches/{batch_id}/`         | -                                                                   |
| `GET /imports/batch/{batch_id}/summary/`                 | `GET /v1/imports/records/{record_id}/batches/{batch_id}/summary/` | -                                                                   |
| `GET /imports/batch/{batch_id}/results/`                 | `GET /v1/imports/records/{record_id}/batches/{batch_id}/results/` | -                                                                   |
| `POST /references/`                                      | REMOVED                                                           | -                                                                   |
| `POST /references/{reference_id}/identifier/`            | REMOVED                                                           | -                                                                   |
| `POST /references/enhancement/batch/`                    | `POST /v1/enhancement-requests/`                                  | -                                                                   |
| `GET /references/enhancement/batch/request/{request_id}` | `GET /v1/enhancement-requests/{request_id}/`                      | -                                                                   |
| `POST /references/index/rebuild/`                        | `POST /v1/system/indices/repair/`                                 | Added query params: `system`, `rebuild`. Status code changed to 202 |
| `POST /robot/enhancement/batch/`                         | `POST /v1/enhancement-requests/{request_id}/results/`             | Status code: 200 if error else 202                                  |
| `POST /robot/{robot_id}/automation/`                     | `POST /v1/enhancement-requests/automations/`                      | -                                                                   |
| `PUT /robot/`                                            | `PUT /v1/robots/{robot_id}/`                                      | Status code changed to 201                                          |
| `POST /robot/`                                           | `POST /v1/robots/`                                                | -                                                                   |
| `GET /robot/{robot_id}/`                                 | `GET /v1/robots/{robot_id}/`                                      | -                                                                   |
| `POST /robot/{robot_id}/secret/`                         | `POST /v1/robots/{robot_id}/secret/`                              | -                                                                   |
| `GET /healthcheck/`                                      | `GET /v1/system/healthcheck/`                                     | -                                                                   |
| Anything else                                            | `/v1/{unchanged-endpoint}/`                                       | -                                                                   |
