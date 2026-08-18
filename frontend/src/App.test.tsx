import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

const csrfToken = "test-csrf-token-that-is-long-enough";
const user = {
  id: "5a1f13aa-92cc-4a20-836b-6b9a7a3c5f11",
  handle: "campus_user",
  email: "campus@example.test",
  verification: { status: "pending_provider_configuration", login_allowed: true },
};
const inactiveLocation = {
  status: "inactive",
  selected_place: null,
  containment_path: [],
  uncertain_places: [],
  selection: { strategy: "recorded_active_visit", reason_code: "NO_ACTIVE_VISIT" },
  visit: null,
};

function jsonResponse(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function envelope(data: unknown): Response {
  return jsonResponse({
    data,
    meta: { schema_version: 1 },
    request_id: "0fb72570-f975-43c4-a038-b2c0c66bed93",
  });
}

function requestPath(input: RequestInfo | URL): string {
  return typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
}

describe("PlacePulse location slice", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
    Reflect.deleteProperty(navigator, "geolocation");
  });

  it("reports a ready gateway and offers account access", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/health/ready") return Promise.resolve(jsonResponse({ status: "ready" }));
      return Promise.resolve(
        envelope({ authenticated: false, user: null, csrf_token: csrfToken }),
      );
    });

    render(<App />);

    expect(screen.getByRole("heading", { name: /places remember/i })).toBeInTheDocument();
    expect(await screen.findByText("The PlacePulse core is online.")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Register" })).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/health/ready",
      expect.objectContaining({ cache: "no-store", credentials: "same-origin" }),
    );
  });

  it("offers a retry when the gateway is unavailable", async () => {
    let healthCalls = 0;
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/health/ready") {
        healthCalls += 1;
        return healthCalls === 1
          ? Promise.reject(new TypeError("network unavailable"))
          : Promise.resolve(jsonResponse({ status: "ready" }));
      }
      return Promise.resolve(
        envelope({ authenticated: false, user: null, csrf_token: csrfToken }),
      );
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(healthCalls).toBe(2);
    });
    expect(await screen.findByText("The PlacePulse core is online.")).toBeInTheDocument();
  });

  it("registers with the session CSRF token and returns to sign in", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/health/ready") return Promise.resolve(jsonResponse({ status: "ready" }));
      if (path === "/api/auth/register") return Promise.resolve(envelope({ user }));
      return Promise.resolve(
        envelope({ authenticated: false, user: null, csrf_token: csrfToken }),
      );
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Register" }));
    fireEvent.change(screen.getByLabelText("Handle"), { target: { value: "campus_user" } });
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: user.email } });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "a-long-test-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    expect(await screen.findByText(/account created/i)).toBeInTheDocument();
    const registration = fetchMock.mock.calls.find(([input]) => requestPath(input) === "/api/auth/register");
    expect(registration?.[1]?.headers).toEqual(
      expect.objectContaining({}),
    );
    expect((registration?.[1]?.headers as Headers).get("X-CSRF-Token")).toBe(csrfToken);
  });

  it("resolves an explicit browser location to Taub and its parent", async () => {
    const taub = {
      id: "2a1f13aa-92cc-4a20-836b-6b9a7a3c5f11",
      name: "Taub Computer Science Building",
      osm_type: "way",
      osm_id: 67222155,
      parent_place_id: "3a1f13aa-92cc-4a20-836b-6b9a7a3c5f11",
    };
    const technion = {
      id: taub.parent_place_id,
      name: "Technion – Israel Institute of Technology",
      osm_type: "way",
      osm_id: 66098525,
      parent_place_id: null,
    };
    const resolved = {
      status: "resolved",
      selected_place: taub,
      containment_path: [taub, technion],
      uncertain_places: [],
      selection: {
        strategy: "deepest_confident_containing",
        reason_code: "DEEPEST_CONFIDENT_PLACE",
      },
      visit: {
        id: "4a1f13aa-92cc-4a20-836b-6b9a7a3c5f11",
        place_id: taub.id,
        entered_at: "2026-08-18T12:00:00Z",
        exited_at: null,
      },
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/health/ready") return Promise.resolve(jsonResponse({ status: "ready" }));
      if (path === "/api/auth/session") {
        return Promise.resolve(envelope({ authenticated: true, user, csrf_token: csrfToken }));
      }
      if (path === "/api/location/current") return Promise.resolve(envelope(inactiveLocation));
      if (path === "/api/location/resolve") return Promise.resolve(envelope(resolved));
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: {
        getCurrentPosition: (success: PositionCallback): void => {
          success({
            coords: {
              latitude: 32.77768,
              longitude: 35.02152,
              accuracy: 5,
              altitude: null,
              altitudeAccuracy: null,
              heading: null,
              speed: null,
              toJSON: () => ({}),
            },
            timestamp: Date.now(),
            toJSON: () => ({}),
          });
        },
      },
    });

    render(<App />);
    expect(await screen.findByText(/email verification is not configured/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Find my place" }));

    expect(await screen.findByRole("heading", { name: taub.name })).toBeInTheDocument();
    expect(screen.getByText(technion.name)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Leave place" })).toBeInTheDocument();
  });

  it("keeps the recorded visit visible after a low-accuracy attempt", async () => {
    const taub = {
      id: "2a1f13aa-92cc-4a20-836b-6b9a7a3c5f11",
      name: "Taub Computer Science Building",
      osm_type: "way",
      osm_id: 67222155,
      parent_place_id: null,
    };
    const current = {
      status: "resolved",
      selected_place: taub,
      containment_path: [taub],
      uncertain_places: [],
      selection: { strategy: "recorded_active_visit", reason_code: "RECORDED_ACTIVE_VISIT" },
      visit: {
        id: "4a1f13aa-92cc-4a20-836b-6b9a7a3c5f11",
        place_id: taub.id,
        entered_at: "2026-08-18T12:00:00Z",
        exited_at: null,
      },
    };
    const lowAccuracy = {
      ...inactiveLocation,
      status: "low_accuracy",
      selection: { strategy: "deepest_confident_containing", reason_code: "ACCURACY_TOO_LOW" },
    };
    vi.spyOn(globalThis, "fetch").mockImplementation((input) => {
      const path = requestPath(input);
      if (path === "/api/health/ready") return Promise.resolve(jsonResponse({ status: "ready" }));
      if (path === "/api/auth/session") {
        return Promise.resolve(envelope({ authenticated: true, user, csrf_token: csrfToken }));
      }
      if (path === "/api/location/current") return Promise.resolve(envelope(current));
      if (path === "/api/location/resolve") return Promise.resolve(envelope(lowAccuracy));
      return Promise.reject(new Error(`Unexpected request: ${path}`));
    });
    Object.defineProperty(navigator, "geolocation", {
      configurable: true,
      value: {
        getCurrentPosition: (success: PositionCallback): void => {
          success({
            coords: {
              latitude: 32.77768,
              longitude: 35.02152,
              accuracy: 150,
              altitude: null,
              altitudeAccuracy: null,
              heading: null,
              speed: null,
              toJSON: () => ({}),
            },
            timestamp: Date.now(),
            toJSON: () => ({}),
          });
        },
      },
    });

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Refresh place" }));

    expect(await screen.findByText(/wider than 100 metres/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: taub.name })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Leave place" })).toBeInTheDocument();
  });
});
