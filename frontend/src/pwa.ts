export interface ServiceWorkerUpdate {
  apply: () => void;
}

export function registerServiceWorker(onUpdate: (update: ServiceWorkerUpdate) => void): void {
  if (!("serviceWorker" in navigator)) {
    return;
  }

  let shouldReload = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (shouldReload) {
      window.location.reload();
    }
  });

  const startRegistration = (): void => {
    void navigator.serviceWorker
      .register("/service-worker.js", { scope: "/", updateViaCache: "none" })
      .then((registration) => {
        const offerUpdate = (worker: ServiceWorker): void => {
          onUpdate({
            apply: () => {
              shouldReload = true;
              worker.postMessage({ type: "SKIP_WAITING" });
            },
          });
        };

        if (registration.waiting !== null && navigator.serviceWorker.controller !== null) {
          offerUpdate(registration.waiting);
        }

        registration.addEventListener("updatefound", () => {
          const worker = registration.installing;
          worker?.addEventListener("statechange", () => {
            if (worker.state === "installed" && navigator.serviceWorker.controller !== null) {
              offerUpdate(worker);
            }
          });
        });
      })
      .catch(() => {
        // The app remains fully usable when registration is unavailable.
      });
  };

  if (document.readyState === "complete") {
    startRegistration();
  } else {
    window.addEventListener("load", startRegistration, { once: true });
  }
}
