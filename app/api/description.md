### Changelog

Here is a summative changelog of each major version. In general only major breaking changes are listed here, additive and backward-compatible changes can and will be made continuously.

#### V1

Key focus: standardisation and sanitation. These are overwhelmingly URL schema changes, not functional changes.

| Old Endpoint                                              | New Endpoint                                                      | Other Changes                                                       |
| --------------------------------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------- |
| `POST /imports/record/`                                   | `POST /imports/records/`                                          | -                                                                   |
| `GET /imports/record/{record_id}/`                        | `GET /imports/records/{record_id}/`                               | -                                                                   |
| `PATCH /imports/record/{record_id}/finalise/`             | `PATCH /imports/records/{record_id}/finalise/`                    | -                                                                   |
| `POST /imports/record/{record_id}/batch/`                 | `POST /imports/records/{record_id}/batches/`                      | -                                                                   |
| `GET /imports/record/{record_id}/batch/`                  | `GET /imports/records/{record_id}/batches/`                       | -                                                                   |
| `GET /imports/batch/{batch_id}/`                          | `GET /imports/records/{record_id}/batches/{batch_id}/`            | -                                                                   |
| `GET /imports/batch/{batch_id}/summary/`                  | `GET /imports/records/{record_id}/batches/{batch_id}/summary/`    | -                                                                   |
| `GET /imports/batch/{batch_id}/results/`                  | `GET /imports/records/{record_id}/batches/{batch_id}/results/`    | -                                                                   |
| `POST /references/`                                       | REMOVED                                                           | -                                                                   |
| `POST /references/{reference_id}/identifier/`             | REMOVED                                                           | -                                                                   |
| `POST /references/enhancement/single/`                    | `POST /enhancement-requests/single-requests/`                     | -                                                                   |
| `POST /references/enhancement/batch/`                     | `POST /enhancement-requests/batch-requests/`                      | -                                                                   |
| `GET /references/enhancement/single/request/{request_id}` | `GET /enhancement-requests/single-requests/{request_id}/`         | -                                                                   |
| `GET /references/enhancement/batch/request/{request_id}`  | `GET /enhancement-requests/batch-requests/{request_id}/`          | -                                                                   |
| `POST /references/index/rebuild/`                         | `POST /system/indices/repair/`                                    | Added query params: `system`, `rebuild`. Status code changed to 202 |
| `POST /robot/enhancement/single/`                         | `POST /enhancement-requests/single-requests/{request_id}/result/` | Status code: 200 if error else 201                                  |
| `POST /robot/enhancement/batch/`                          | `POST /enhancement-requests/batch-requests/{request_id}/result/`  | Status code: 200 if error else 202                                  |
| `POST /robot/{robot_id}/automation/`                      | `POST /enhancement-requests/automations/`                         | -                                                                   |
| `PUT /robot/`                                             | `PUT /robots/{robot_id}/`                                         | Status code changed to 201                                          |
| `POST /robot/`                                            | `POST /robots/`                                                   | -                                                                   |
| `GET /robot/{robot_id}/`                                  | `GET /robots/{robot_id}/`                                         | -                                                                   |
| `POST /robot/{robot_id}/secret/`                          | `POST /robots/{robot_id}/secret/`                                 | -                                                                   |
| `GET /healthcheck/`                                       | `GET /system/healthcheck/`                                        | -                                                                   |
