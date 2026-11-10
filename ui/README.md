# DESTINY Repository UI

A [Preact](https://preactjs.com/) single-page app built with
[Vite](https://vite.dev/). It is deployed as static files to Azure Blob Storage
behind Front Door, so there is no server-side component.

This is very much a work in progress!

## Getting Started

### Docker Compose

From the repository root (above `ui`), run the UI alongside the API:

```sh
docker compose --profile search --profile app --profile ui up
```

The UI will be available at <http://localhost:3000>. Sign-in is disabled, which
matches the API running with `ENV=local`.

### NPM

```sh
cp .env.example .env
npm install
npm run dev
```

The UI will be available at <http://localhost:3000>.

To exercise sign-in locally, start Keycloak with
`docker compose --profile keycloak up`, run the API with `ENV` set to anything
but `local`, then remove `VITE_AUTH_DISABLED` from `.env` and uncomment the
`VITE_KEYCLOAK_*` values.

## Configuration

Configuration is read from `VITE_*` environment variables **at build time** and
inlined into the bundle. A deployed build therefore belongs to one environment:
the deploy workflow rebuilds the UI for each environment rather than promoting
a build between them. `npm run build` fails if a required variable is missing.

| Variable                  | Purpose                                               |
| ------------------------- | ----------------------------------------------------- |
| `VITE_API_BASE`           | API base URL including the version prefix (`.../v1`). |
| `VITE_KEYCLOAK_URL`       | Keycloak base URL.                                    |
| `VITE_KEYCLOAK_REALM`     | Keycloak realm.                                       |
| `VITE_KEYCLOAK_CLIENT_ID` | Public Keycloak client for this UI.                   |
| `VITE_AUTH_DISABLED`      | `true` skips sign-in. Local development only.         |

## Checks

```sh
npm run typecheck
npm test
npm run build
```
