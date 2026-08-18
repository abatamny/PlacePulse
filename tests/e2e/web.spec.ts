import { expect, test } from "@playwright/test";

test("serves the responsive shell and API through Caddy", async ({ page, request }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const pageResponse = await page.goto("/future/place-route");
  expect(pageResponse?.status()).toBe(200);

  await expect(page.getByRole("heading", { name: /places remember/i })).toBeVisible();
  await expect(page.getByText("The PlacePulse core is online.")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );

  const apiResponse = await request.get("/api/health/live");
  expect(apiResponse.status()).toBe(200);
  await expect(apiResponse.json()).resolves.toEqual({ status: "ok" });
});

test("applies gateway security, compression, and request limits", async ({ request }) => {
  const shellResponse = await request.get("/", {
    headers: { "Accept-Encoding": "gzip" },
  });
  const headers = shellResponse.headers();
  expect(headers["content-security-policy"]).toContain("default-src 'self'");
  expect(headers["x-content-type-options"]).toBe("nosniff");
  expect(headers["x-frame-options"]).toBe("DENY");
  expect(headers["content-encoding"]).toBe("gzip");
  expect(headers.server).toBeUndefined();

  const oversized = await request.post("/api/_test/body", {
    data: "x".repeat(1_100_000),
    headers: { "Content-Type": "text/plain" },
  });
  expect(oversized.status()).toBe(413);
});

test("proxies a WebSocket upgrade without exposing milestone 5 behavior", async ({ page }) => {
  await page.goto("/");
  const echoed = await page.evaluate(
    () =>
      new Promise<string>((resolve, reject) => {
        const scheme = window.location.protocol === "https:" ? "wss" : "ws";
        const websocket = new WebSocket(`${scheme}://${window.location.host}/ws/_test/echo`);
        const timeout = window.setTimeout(() => {
          websocket.close();
          reject(new Error("WebSocket transport probe timed out"));
        }, 5_000);
        websocket.addEventListener("open", () => {
          websocket.send("placepulse-websocket-probe");
        });
        websocket.addEventListener("message", (event) => {
          window.clearTimeout(timeout);
          resolve(String(event.data));
        });
        websocket.addEventListener("error", () => {
          window.clearTimeout(timeout);
          reject(new Error("WebSocket transport probe failed"));
        });
      }),
  );
  expect(echoed).toBe("placepulse-websocket-probe");
});

test("keeps API responses out of the service-worker cache and serves the shell offline", async ({
  context,
  page,
}) => {
  await page.goto("/");
  const activationState = await page.evaluate(async () => {
    const registration = await navigator.serviceWorker.register("/service-worker.js", {
      scope: "/",
      updateViaCache: "none",
    });
    if (registration.active !== null) {
      return registration.active.state;
    }

    const worker = registration.installing ?? registration.waiting;
    if (worker === null) {
      return "missing";
    }

    return new Promise<string>((resolve) => {
      const timeout = window.setTimeout(() => {
        resolve(`timeout:${worker.state}`);
      }, 5_000);
      worker.addEventListener("statechange", () => {
        if (worker.state === "activated" || worker.state === "redundant") {
          window.clearTimeout(timeout);
          resolve(worker.state);
        }
      });
    });
  });
  expect(activationState).toBe("activated");
  await page.reload();
  expect(await page.evaluate(() => navigator.serviceWorker.controller !== null)).toBe(true);

  await page.evaluate(() => fetch("/api/health/live"));
  const cachedUrls = await page.evaluate(async () => {
    const cacheNames = await caches.keys();
    const requests = await Promise.all(
      cacheNames.map(async (cacheName) => {
        const cache = await caches.open(cacheName);
        return cache.keys();
      }),
    );
    return requests.flat().map((request) => request.url);
  });
  expect(cachedUrls.some((url) => new URL(url).pathname.startsWith("/api/"))).toBe(false);

  await context.setOffline(true);
  try {
    await page.goto("/offline-proof");
    await expect(page.getByRole("heading", { name: /places remember/i })).toBeVisible();
  } finally {
    await context.setOffline(false);
  }
});
