export type ApiState = "checking" | "ready" | "unavailable";
export type VerificationStatus = "pending_provider_configuration" | "verified";
export type LocationStatus = "resolved" | "unknown" | "ambiguous" | "low_accuracy" | "inactive";

export interface UserView {
  id: string;
  handle: string;
  email: string;
  verification: {
    status: VerificationStatus;
    login_allowed: boolean;
  };
}

export interface PlaceView {
  id: string;
  name: string;
  osm_type: "node" | "way" | "relation";
  osm_id: number;
  parent_place_id: string | null;
}

export interface VisitView {
  id: string;
  place_id: string;
  entered_at: string;
  exited_at: string | null;
}

export interface LocationData {
  status: LocationStatus;
  selected_place: PlaceView | null;
  containment_path: PlaceView[];
  uncertain_places: PlaceView[];
  selection: {
    strategy: "deepest_confident_containing" | "recorded_active_visit";
    reason_code: string;
  };
  visit: VisitView | null;
}

interface ReadinessResponse {
  status: "ready" | "unavailable";
}

interface ApiEnvelope<T> {
  data: T;
  meta: { schema_version: 1 };
  request_id: string;
}

interface ApiErrorEnvelope {
  error: {
    code: string;
    message: string;
    details: unknown;
  };
  request_id: string;
}

interface SessionData {
  authenticated: boolean;
  user: UserView | null;
  csrf_token: string;
}

let csrfToken: string | null = null;

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = init.method?.toUpperCase() ?? "GET";
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body !== undefined) {
    headers.set("Content-Type", "application/json");
  }
  if (!["GET", "HEAD"].includes(method)) {
    if (csrfToken === null) {
      throw new ApiError("CSRF_UNAVAILABLE", "The secure session is not ready yet.", 0);
    }
    headers.set("X-CSRF-Token", csrfToken);
  }

  const response = await fetch(path, {
    ...init,
    headers,
    cache: "no-store",
    credentials: "same-origin",
  });
  const body = (await response.json()) as ApiEnvelope<T> | ApiErrorEnvelope;
  if (!response.ok || "error" in body) {
    const error = "error" in body ? body.error : null;
    throw new ApiError(
      error?.code ?? "REQUEST_FAILED",
      error?.message ?? "The request could not be completed.",
      response.status,
    );
  }
  return body.data;
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

export async function getSession(): Promise<SessionData> {
  const session = await apiRequest<SessionData>("/api/auth/session");
  csrfToken = session.csrf_token;
  return session;
}

export async function registerAccount(input: {
  handle: string;
  email: string;
  password: string;
}): Promise<UserView> {
  const data = await apiRequest<{ user: UserView }>("/api/auth/register", {
    method: "POST",
    body: JSON.stringify(input),
  });
  return data.user;
}

export async function loginAccount(input: {
  email: string;
  password: string;
}): Promise<UserView> {
  const data = await apiRequest<SessionData>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify(input),
  });
  csrfToken = data.csrf_token;
  if (!data.authenticated || data.user === null) {
    throw new ApiError("INVALID_SESSION", "The session could not be created.", 500);
  }
  return data.user;
}

export async function logoutAccount(): Promise<void> {
  await apiRequest<{ logged_out: true }>("/api/auth/logout", { method: "POST" });
  csrfToken = null;
}

export async function getCurrentLocation(): Promise<LocationData> {
  return apiRequest<LocationData>("/api/location/current");
}

export async function resolveLocation(input: {
  latitude: number;
  longitude: number;
  accuracy_meters: number;
}): Promise<LocationData> {
  return apiRequest<LocationData>("/api/location/resolve", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function leaveLocation(): Promise<LocationData> {
  return apiRequest<LocationData>("/api/location/leave", { method: "POST" });
}
