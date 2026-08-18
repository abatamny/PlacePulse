import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

describe("PlacePulse shell", () => {
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("reports a ready API through the same-origin gateway", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ready" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    render(<App />);

    expect(screen.getByRole("heading", { name: /places remember/i })).toBeInTheDocument();
    expect(await screen.findByText("The PlacePulse core is online.")).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith(
      "/api/health/ready",
      expect.objectContaining({ cache: "no-store", credentials: "same-origin" }),
    );
  });

  it("offers a retry when the API is unavailable", async () => {
    const readiness = vi
      .spyOn(globalThis, "fetch")
      .mockRejectedValueOnce(new TypeError("network unavailable"))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ status: "ready" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );

    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(readiness).toHaveBeenCalledTimes(2);
    });
    expect(await screen.findByText("The PlacePulse core is online.")).toBeInTheDocument();
  });
});
