let cachedConfig: Record<string, string> = {};

export async function getRuntimeConfig(): Promise<Record<string, string>> {
  if (Object.keys(cachedConfig).length > 0) {
    return cachedConfig;
  }
  const res = await fetch("/runtime-config.json");
  if (!res.ok) throw new Error("runtime-config.json not found");
  const config = await res.json();
  cachedConfig = config;
  return cachedConfig;
}

export function getBaseApiUrl(): string | undefined {
  return cachedConfig["NEXT_PUBLIC_API_URL"];
}
