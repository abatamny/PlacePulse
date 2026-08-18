import { useCallback, useEffect, useState } from "react";

import { type ApiState, checkApiReadiness } from "./api";
import { type ServiceWorkerUpdate, registerServiceWorker } from "./pwa";

const statusCopy: Record<ApiState, { label: string; detail: string }> = {
  checking: {
    label: "Connecting",
    detail: "Checking the PlacePulse gateway…",
  },
  ready: {
    label: "Ready",
    detail: "The PlacePulse core is online.",
  },
  unavailable: {
    label: "Unavailable",
    detail: "The core is not responding yet.",
  },
};

function useOnlineState(): boolean {
  const [isOnline, setIsOnline] = useState(() => navigator.onLine);

  useEffect(() => {
    const goOnline = (): void => {
      setIsOnline(true);
    };
    const goOffline = (): void => {
      setIsOnline(false);
    };
    window.addEventListener("online", goOnline);
    window.addEventListener("offline", goOffline);
    return () => {
      window.removeEventListener("online", goOnline);
      window.removeEventListener("offline", goOffline);
    };
  }, []);

  return isOnline;
}

export function App(): React.JSX.Element {
  const [apiState, setApiState] = useState<ApiState>("checking");
  const [checkSequence, setCheckSequence] = useState(0);
  const [update, setUpdate] = useState<ServiceWorkerUpdate | null>(null);
  const isOnline = useOnlineState();

  const retry = useCallback(() => {
    setApiState("checking");
    setCheckSequence((current) => current + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      controller.abort();
    }, 4_000);
    void checkApiReadiness(controller.signal)
      .then((ready) => {
        setApiState(ready ? "ready" : "unavailable");
      })
      .catch(() => {
        setApiState("unavailable");
      })
      .finally(() => {
        window.clearTimeout(timeout);
      });
    return () => {
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [checkSequence]);

  useEffect(() => {
    registerServiceWorker(setUpdate);
  }, []);

  const copy = statusCopy[apiState];

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="PlacePulse home">
          <span className="brand-mark" aria-hidden="true">
            <span className="brand-pulse" />
          </span>
          <span>PlacePulse</span>
        </a>
        <span className={`network-pill ${isOnline ? "is-online" : "is-offline"}`}>
          <span className="network-dot" aria-hidden="true" />
          {isOnline ? "Online" : "Offline"}
        </span>
      </header>

      <main>
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-copy">
            <p className="eyebrow">A social map of right now</p>
            <h1 id="hero-title">
              Places remember.
              <span>People connect.</span>
            </h1>
            <p className="hero-description">
              PlacePulse makes the place around you the center of the conversation—while
              keeping the infrastructure behind it private by default.
            </p>

            <div className={`service-status status-${apiState}`} aria-live="polite">
              <span className="status-orbit" aria-hidden="true">
                <span className="status-core" />
              </span>
              <span className="status-message">
                <strong>{copy.label}</strong>
                <span>{isOnline ? copy.detail : "The app shell remains available offline."}</span>
              </span>
              {apiState === "unavailable" && isOnline ? (
                <button type="button" onClick={retry}>
                  Retry
                </button>
              ) : null}
            </div>
          </div>

          <div className="place-radar" aria-hidden="true">
            <span className="radar-ring ring-one" />
            <span className="radar-ring ring-two" />
            <span className="radar-ring ring-three" />
            <span className="place-pin">
              <span />
            </span>
            <span className="radar-label label-near">Here</span>
            <span className="radar-label label-place">Your place</span>
          </div>
        </section>

        <section className="principles" aria-label="PlacePulse principles">
          <article>
            <span className="principle-number">01</span>
            <h2>Place first</h2>
            <p>What happens here belongs to the context of here—not a popularity feed.</p>
          </article>
          <article>
            <span className="principle-number">02</span>
            <h2>Present tense</h2>
            <p>Live connection follows real foreground presence and expires when you leave.</p>
          </article>
          <article>
            <span className="principle-number">03</span>
            <h2>Private routes</h2>
            <p>Your browser reaches one secure gateway; internal services stay internal.</p>
          </article>
        </section>
      </main>

      <footer>
        <p>Built for shared places, from the ground up.</p>
        <span>PlacePulse web foundation</span>
      </footer>

      {update !== null ? (
        <aside className="update-toast" aria-live="polite">
          <span>A new PlacePulse version is ready.</span>
          <button type="button" onClick={update.apply}>
            Update now
          </button>
        </aside>
      ) : null}
    </div>
  );
}
