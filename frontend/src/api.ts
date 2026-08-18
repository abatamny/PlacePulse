export type ApiState = "checking" | "ready" | "unavailable";

interface ReadinessResponse {
  status: "ready" | "unavailable";
}

export async function checkApiReadiness(signal: AbortSignal): Promise<boolean> {
  const response = await fetch("/api/health/ready", {
    headers: { Accept: "application/json" },
    cache: "no-store",
    credentials: "same-origin",
    signal,
  });
  if (!response.ok) {
    return false;
  }

  const body = (await response.json()) as ReadinessResponse;
  return body.status === "ready";
}
