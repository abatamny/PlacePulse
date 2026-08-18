import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  type ApiState,
  type LocationData,
  type UserView,
  checkApiReadiness,
  getCurrentLocation,
  getSession,
  leaveLocation,
  loginAccount,
  logoutAccount,
  registerAccount,
  resolveLocation,
} from "./api";
import { type ServiceWorkerUpdate, registerServiceWorker } from "./pwa";

type AuthMode = "login" | "register";
type BrowserLocationState = "idle" | "requesting" | "denied" | "unavailable" | "timeout";

const statusCopy: Record<ApiState, { label: string; detail: string }> = {
  checking: { label: "Connecting", detail: "Checking the PlacePulse gateway…" },
  ready: { label: "Ready", detail: "The PlacePulse core is online." },
  unavailable: { label: "Unavailable", detail: "The core is not responding yet." },
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

function messageForLocation(
  browserState: BrowserLocationState,
  location: LocationData | null,
): string {
  if (browserState === "requesting") return "Requesting a one-time location fix…";
  if (browserState === "denied") return "Location permission was denied. You can enable it and try again.";
  if (browserState === "timeout") return "The browser could not get a location in time. Try again outdoors or near a window.";
  if (browserState === "unavailable") return "This browser could not provide a location.";
  if (location?.status === "low_accuracy") return "The location radius is wider than 100 metres, so no place was selected.";
  if (location?.status === "ambiguous") return "Your accuracy radius crosses a place boundary. No new visit was recorded.";
  if (location?.status === "unknown") return "You are outside the reviewed PlacePulse places.";
  if (location?.status === "inactive") return "No place visit is currently recorded.";
  return "Share a one-time location fix to find the most specific place we can confirm.";
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  return "Something went wrong. Please try again.";
}

export function App(): React.JSX.Element {
  const [apiState, setApiState] = useState<ApiState>("checking");
  const [checkSequence, setCheckSequence] = useState(0);
  const [update, setUpdate] = useState<ServiceWorkerUpdate | null>(null);
  const [sessionLoading, setSessionLoading] = useState(true);
  const [user, setUser] = useState<UserView | null>(null);
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [handle, setHandle] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [location, setLocation] = useState<LocationData | null>(null);
  const [lastResolution, setLastResolution] = useState<LocationData | null>(null);
  const [browserLocation, setBrowserLocation] = useState<BrowserLocationState>("idle");
  const [lastAccuracy, setLastAccuracy] = useState<number | null>(null);
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
    let cancelled = false;
    void getSession()
      .then(async (session) => {
        if (cancelled) return;
        setUser(session.user);
        if (session.user !== null) {
          const current = await getCurrentLocation();
          setLocation(current);
          setLastResolution(current);
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(errorMessage(reason));
      })
      .finally(() => {
        if (!cancelled) setSessionLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    registerServiceWorker(setUpdate);
  }, []);

  const submitAuth = async (event: React.SyntheticEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      if (authMode === "register") {
        await registerAccount({ handle, email, password });
        setAuthMode("login");
        setPassword("");
        setNotice("Account created. Sign in with the email and password you just chose.");
      } else {
        const loggedIn = await loginAccount({ email, password });
        setUser(loggedIn);
        setPassword("");
        const current = await getCurrentLocation();
        setLocation(current);
        setLastResolution(current);
      }
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const logOut = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      await logoutAccount();
      setUser(null);
      setLocation(null);
      setLastResolution(null);
      setLastAccuracy(null);
      await getSession();
      setNotice("You are signed out and the recorded visit has ended.");
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const findPlace = (): void => {
    setError(null);
    setNotice(null);
    if (!isOnline) {
      setError("Reconnect before requesting a place.");
      return;
    }
    if (!("geolocation" in navigator)) {
      setBrowserLocation("unavailable");
      return;
    }
    setBusy(true);
    setBrowserLocation("requesting");
    navigator.geolocation.getCurrentPosition(
      (position) => {
        const accuracy = position.coords.accuracy;
        setLastAccuracy(accuracy);
        void resolveLocation({
          latitude: position.coords.latitude,
          longitude: position.coords.longitude,
          accuracy_meters: accuracy,
        })
          .then((resolved) => {
            setLastResolution(resolved);
            if (resolved.status !== "low_accuracy" && resolved.status !== "ambiguous") {
              setLocation(resolved);
            }
            setBrowserLocation("idle");
          })
          .catch((reason: unknown) => {
            setError(errorMessage(reason));
            setBrowserLocation("idle");
          })
          .finally(() => {
            setBusy(false);
          });
      },
      (locationError) => {
        if (locationError.code === locationError.PERMISSION_DENIED) setBrowserLocation("denied");
        else if (locationError.code === locationError.TIMEOUT) setBrowserLocation("timeout");
        else setBrowserLocation("unavailable");
        setBusy(false);
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 10_000 },
    );
  };

  const leave = async (): Promise<void> => {
    setBusy(true);
    setError(null);
    try {
      const inactive = await leaveLocation();
      setLocation(inactive);
      setLastResolution(inactive);
      setLastAccuracy(null);
      setNotice("Your recorded visit has ended.");
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const copy = statusCopy[apiState];
  const locationMessage = messageForLocation(browserLocation, lastResolution ?? location);

  return (
    <div className="app-shell">
      <header className="site-header">
        <a className="brand" href="/" aria-label="PlacePulse home">
          <span className="brand-mark" aria-hidden="true"><span className="brand-pulse" /></span>
          <span>PlacePulse</span>
        </a>
        <div className="header-actions">
          {user !== null ? <span className="signed-in-handle">@{user.handle}</span> : null}
          <span className={`network-pill ${isOnline ? "is-online" : "is-offline"}`}>
            <span className="network-dot" aria-hidden="true" />
            {isOnline ? "Online" : "Offline"}
          </span>
        </div>
      </header>

      <main>
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-copy">
            <p className="eyebrow">A social map of right now</p>
            <h1 id="hero-title">Places remember.<span>People connect.</span></h1>
            <p className="hero-description">
              Sign in, share a one-time location fix, and see the reviewed physical place around you.
            </p>
            <div className={`service-status status-${apiState}`} aria-live="polite">
              <span className="status-orbit" aria-hidden="true"><span className="status-core" /></span>
              <span className="status-message">
                <strong>{copy.label}</strong>
                <span>{isOnline ? copy.detail : "The app shell remains available offline."}</span>
              </span>
              {apiState === "unavailable" && isOnline ? <button type="button" onClick={retry}>Retry</button> : null}
            </div>
          </div>

          <section className="experience-panel" aria-label={user === null ? "Account access" : "Current place"}>
            {sessionLoading ? (
              <div className="panel-loading" role="status">Restoring your secure session…</div>
            ) : user === null ? (
              <>
                <div className="auth-tabs" aria-label="Account action">
                  <button type="button" className={authMode === "login" ? "is-active" : ""} onClick={() => { setAuthMode("login"); }}>Sign in</button>
                  <button type="button" className={authMode === "register" ? "is-active" : ""} onClick={() => { setAuthMode("register"); }}>Register</button>
                </div>
                <div className="panel-heading">
                  <p className="panel-kicker">{authMode === "login" ? "Welcome back" : "Join PlacePulse"}</p>
                  <h2>{authMode === "login" ? "Find your place" : "Create your account"}</h2>
                </div>
                <form className="auth-form" onSubmit={(event) => void submitAuth(event)}>
                  {authMode === "register" ? (
                    <label>Handle<input name="handle" autoComplete="username" required minLength={3} maxLength={32} pattern="[A-Za-z0-9_]+" value={handle} onChange={(event) => { setHandle(event.target.value); }} /></label>
                  ) : null}
                  <label>Email<input name="email" type="email" autoComplete="email" required value={email} onChange={(event) => { setEmail(event.target.value); }} /></label>
                  <label>Password<input name="password" type="password" autoComplete={authMode === "login" ? "current-password" : "new-password"} required minLength={12} maxLength={128} value={password} onChange={(event) => { setPassword(event.target.value); }} /></label>
                  <button className="primary-action" type="submit" disabled={busy || !isOnline}>{busy ? "Working…" : authMode === "login" ? "Sign in" : "Create account"}</button>
                </form>
              </>
            ) : (
              <>
                <div className="account-row">
                  <div><span>Signed in as</span><strong>@{user.handle}</strong></div>
                  <button className="text-action" type="button" disabled={busy || !isOnline} onClick={() => void logOut()}>Sign out</button>
                </div>
                {user.verification.status === "pending_provider_configuration" ? (
                  <p className="verification-note">Email verification is not configured yet. This provisional course build allows sign-in without marking your email verified.</p>
                ) : null}
                <div className="place-card" aria-live="polite">
                  <p className="panel-kicker">Current recorded place</p>
                  {location?.status === "resolved" && location.selected_place !== null ? (
                    <>
                      <h2>{location.selected_place.name}</h2>
                      <ol className="place-path" aria-label="Place hierarchy">
                        {location.containment_path.map((place) => <li key={place.id}>{place.name}</li>)}
                      </ol>
                      <p className="place-explanation">
                        {location.selection.reason_code === "PARENT_SELECTED_FOR_ACCURACY"
                          ? "A broader parent was selected because the accuracy radius crossed a nested boundary."
                          : location.selection.reason_code === "RECORDED_ACTIVE_VISIT"
                            ? "Restored from your active recorded visit without requesting coordinates again."
                            : "Selected as the deepest place fully supported by the reported accuracy."}
                      </p>
                      {location.visit !== null ? <p className="visit-time">Entered {new Date(location.visit.entered_at).toLocaleString()}</p> : null}
                    </>
                  ) : <h2>Location not set</h2>}
                  <p className="location-message">{locationMessage}</p>
                  {lastAccuracy !== null ? <p className="accuracy-note">Last browser accuracy: about {Math.round(lastAccuracy)} m</p> : null}
                  {lastResolution?.uncertain_places.length ? <p className="uncertain-note">Boundary uncertainty: {lastResolution.uncertain_places.map((place) => place.name).join(", ")}</p> : null}
                </div>
                <div className="place-actions">
                  <button className="primary-action" type="button" disabled={busy || !isOnline} onClick={findPlace}>{browserLocation === "requesting" ? "Finding…" : location?.status === "resolved" ? "Refresh place" : "Find my place"}</button>
                  {location?.visit?.exited_at === null ? <button className="secondary-action" type="button" disabled={busy || !isOnline} onClick={() => void leave()}>Leave place</button> : null}
                </div>
                <p className="privacy-note">PlacePulse requests location only when you tap the button. Milestone 4 does not track background presence.</p>
              </>
            )}
            {notice !== null ? <p className="form-notice" role="status">{notice}</p> : null}
            {error !== null ? <p className="form-error" role="alert">{error}</p> : null}
          </section>
        </section>

        <section className="principles" aria-label="Location guarantees">
          <article><span className="principle-number">01</span><h2>Verified geography</h2><p>Only reviewed OpenStreetMap polygons in PostGIS can become a place.</p></article>
          <article><span className="principle-number">02</span><h2>Accuracy aware</h2><p>Uncertain coordinates produce a broader place or an honest ambiguous result.</p></article>
          <article><span className="principle-number">03</span><h2>Explicit visits</h2><p>Visits change only when you locate again, leave, or sign out.</p></article>
        </section>
      </main>

      <footer><p>Built for shared places, from the ground up.</p><span>PlacePulse location slice</span></footer>

      {update !== null ? <aside className="update-toast" aria-live="polite"><span>A new PlacePulse version is ready.</span><button type="button" onClick={update.apply}>Update now</button></aside> : null}
    </div>
  );
}
