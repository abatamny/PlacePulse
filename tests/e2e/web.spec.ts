import { expect, test } from "@playwright/test";

test("completes the mobile registration, provisional login, and location flow", async ({
  context,
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Find your place" })).toBeVisible();

  const suffix = `${Date.now().toString(36)}${Math.floor(Math.random() * 10_000)}`;
  const handle = `e2e_${suffix}`.slice(0, 32);
  const email = `${handle}@example.test`;
  const password = "milestone-four-e2e-password";

  await page.getByRole("button", { name: "Register", exact: true }).click();
  await page.getByLabel("Handle").fill(handle);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("Account created. Sign in with the email and password you just chose.")).toBeVisible();

  await page.getByLabel("Password").fill(password);
  await page.locator("form").getByRole("button", { name: "Sign in", exact: true }).click();
  await expect(page.getByText("Email verification is not configured yet.", { exact: false })).toBeVisible();

  await context.grantPermissions(["geolocation"]);
  await context.setGeolocation({ latitude: 32.77768, longitude: 35.02152, accuracy: 2 });
  await page.getByRole("button", { name: "Find my place" }).click();
  await expect(page.getByRole("heading", { name: "Taub Computer Science Building" })).toBeVisible();
  await expect(page.getByRole("list", { name: "Place hierarchy" })).toContainText(
    "Technion – Israel Institute of Technology",
  );
  await expect(page.getByText(/^Entered /)).toBeVisible();

  await page.reload();
  await expect(page.getByRole("heading", { name: "Taub Computer Science Building" })).toBeVisible();
  await page.getByRole("button", { name: "Leave place" }).click();
  await expect(page.getByText("Your recorded visit has ended.")).toBeVisible();

  await context.setGeolocation({ latitude: 32.77768, longitude: 35.02152, accuracy: 150 });
  await page.getByRole("button", { name: "Find my place" }).click();
  await expect(page.getByText("The location radius is wider than 100 metres", { exact: false })).toBeVisible();

  await context.setGeolocation({ latitude: 0, longitude: 0, accuracy: 5 });
  await page.getByRole("button", { name: "Find my place" }).click();
  await expect(page.getByText("You are outside the reviewed PlacePulse places.")).toBeVisible();

  await context.setGeolocation({ latitude: 32.7784636, longitude: 35.0152537, accuracy: 2 });
  await page.getByRole("button", { name: "Find my place" }).click();
  await expect(page.getByText("Your accuracy radius crosses a place boundary.", { exact: false })).toBeVisible();

  await page.route("**/api/location/resolve", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 250));
    await route.continue();
  });
  await context.setGeolocation({ latitude: 32.77768, longitude: 35.02152, accuracy: 2 });
  const locateButton = page.getByRole("button", { name: "Find my place" });
  await locateButton.click();
  await expect(page.getByRole("button", { name: "Finding…" })).toBeDisabled();
  await expect(page.getByRole("heading", { name: "Taub Computer Science Building" })).toBeVisible();
  await page.unroute("**/api/location/resolve");

  await context.setOffline(true);
  await expect(page.getByText("Offline", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh place" })).toBeDisabled();
  await context.setOffline(false);

  await context.clearPermissions();
  await page.getByRole("button", { name: "Refresh place" }).click();
  await expect(page.getByText("Location permission was denied.", { exact: false })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Find your place" })).toBeVisible();
});

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

  const clientIp = await request.get("/api/_test/client-ip", {
    headers: { "X-PlacePulse-Client-IP": "203.0.113.99" },
  });
  expect(clientIp.status()).toBe(200);
  expect((await clientIp.json()).client_ip).not.toBe("203.0.113.99");
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
    await navigator.serviceWorker.register("/service-worker.js", {
      scope: "/",
      updateViaCache: "none",
    });
    const registration = await navigator.serviceWorker.ready;
    const worker = registration.active;
    if (worker === null || worker.state === "activated") {
      return worker?.state ?? "missing";
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
