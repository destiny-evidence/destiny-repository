let cachedConfig: Record<string, string> = {};

export async function getRuntimeConfig(): Promise<Record<string, string>> {
  if (Object.keys(cachedConfig).length > 0) {
    return cachedConfig;
  }
  try {
    // Try to fetch the config file (works in browser and Next.js public folder)
    const res = await fetch("/runtime-config.json");
    if (!res.ok) throw new Error("runtime-config.json not found");
    const config = await res.json();
    cachedConfig = config;
  } catch (err) {
    console.warn(
      "[runtimeConfig] runtime-config.json not found or failed to load, using process.env only",
    );
    cachedConfig = {};
    // Merge process.env keys
    for (const key of Object.keys(process.env)) {
      if (typeof process.env[key] === "string") {
        cachedConfig[key] = process.env[key] as string;
        console.warn(
          `[runtimeConfig] ${key} not found in runtime config, using process.env.${key}`,
        );
      }
    }
  }
  return cachedConfig;
}

export function getBaseApiUrl(): string | undefined {
  return cachedConfig["NEXT_PUBLIC_API_URL"];
}
