import { defineConfig, loadEnv } from "vite";
import preact from "@preact/preset-vite";
import { resolve } from "path";

// Vite inlines these into the bundle, so a missing value only surfaces once the
// deployed page loads. Fail the build instead.
function assertBuildEnv(env: Record<string, string>) {
  const required = ["VITE_API_BASE"];
  if (env.VITE_AUTH_DISABLED !== "true") {
    required.push(
      "VITE_KEYCLOAK_URL",
      "VITE_KEYCLOAK_REALM",
      "VITE_KEYCLOAK_CLIENT_ID",
    );
  }
  const missing = required.filter((name) => !env[name]);
  if (missing.length > 0) {
    throw new Error(
      `Missing required environment variables: ${missing.join(", ")}`,
    );
  }
}

export default defineConfig(({ command, mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  if (command === "build") {
    assertBuildEnv(env);
  }
  return {
    plugins: [preact()],
    resolve: {
      alias: {
        "@": resolve(__dirname, "./src"),
      },
    },
    server: {
      port: 3000,
    },
  };
});
