# DESTINY Repository UI

This is very much a work in progress!

## Getting Started

### Docker Compose (Recommended)

To run with docker, run the below from the application root directory (above `ui`):

```sh
docker compose --profile search --profile app --profile ui up
```

The UI will be available at localhost:3000.

### NPM

To run locally with npm, run the below:

```sh
cp public/runtime-config.json.example public/runtime-config.json
npm run dev
```

The UI will be available at localhost:3000.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.
