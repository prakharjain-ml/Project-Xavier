// Start, jaw calibration, error and disconnected screens. Core only: Xavier needs the Pixel (room camera), the
// Mac webcam (eyes) and the OpenBCI headset; the backend refuses to start without them and says which is missing.
import type { Telemetry } from "./types";

type Act = (type: string, fields?: Record<string, unknown>) => void;

// Same cameras as demo.sh: Pixel = 0 (room), Mac webcam = 1 (eyes).
const FORWARD_CAMERA = 0;
const EYE_CAMERA = 1;

interface Check {
  key: "phone_camera" | "headset_wifi" | "eye_calibration" | "chair";
  name: string;
  ok: string;
  missing: string;
  required: boolean;
}

// What each row checks is real and read-only (interface/web/server.py device_readiness). The headset row only
// knows the laptop is on the OpenBCI Wi-Fi; whether the board answers is checked when Start is pressed.
const CHECKS: Check[] = [
  { key: "phone_camera", name: "Pixel camera", ok: "Connected", missing: "Plug in the Pixel (USB webcam mode)", required: true },
  { key: "headset_wifi", name: "OpenBCI headset", ok: "On the headset Wi-Fi", missing: "Join the OpenBCI-xxxx Wi-Fi", required: true },
  { key: "eye_calibration", name: "Eye calibration", ok: "Saved", missing: "No saved calibration", required: true },
  { key: "chair", name: "Chair", ok: "Connected", missing: "Not connected: wheels will not move", required: false },
];

export function Start({ t, act, busy }: { t: Telemetry; act: Act; busy: boolean }) {
  const ready = t.ready ?? {};
  const blocked = CHECKS.some((c) => c.required && !ready[c.key]);
  return (
    <main className="page">
      <section className="card checklist" aria-labelledby="start-title">
        <h2 id="start-title">Devices</h2>
        <ul>
          {CHECKS.map((c) => {
            const ok = Boolean(ready[c.key]);
            return (
              <li key={c.key} className={ok ? "ok" : c.required ? "bad" : "off"}>
                <span className="dot" aria-hidden="true" />
                <span className="name">{c.name}</span>
                <span className="state">{ok ? c.ok : c.missing}</span>
              </li>
            );
          })}
        </ul>
        <button className="btn primary lg" disabled={busy || blocked}
                onClick={() => act("start_session", { mode: "live", confirm: "jaw", forward_camera: FORWARD_CAMERA, eye_camera: EYE_CAMERA })}>
          {busy ? "Connecting to the headset…" : "Start"}
        </button>
      </section>
    </main>
  );
}

export function JawCalibration({ t, act }: { t: Telemetry; act: Act }) {
  const prompt = t.jaw.prompt ?? "Connecting to the headset…";
  return (
    <main className="page">
      <section className="card center" aria-live="assertive" aria-labelledby="jaw-title">
        <div className="eyebrow">Headset calibration</div>
        <h1 id="jaw-title">{prompt}</h1>
        <button className="btn ghost" onClick={() => act("end_session")}>Cancel</button>
      </section>
    </main>
  );
}

export function ErrorScreen({ t, act }: { t: Telemetry; act: Act }) {
  return (
    <main className="page">
      <section className="card center" role="alert" aria-labelledby="err-title">
        <h2 id="err-title">Stopped</h2>
        <p className="lead">{t.error}</p>
        <button className="btn primary lg" onClick={() => act("end_session")} autoFocus>Back</button>
      </section>
    </main>
  );
}

export function Disconnected() {
  return (
    <main className="page">
      <section className="card center" role="alert" aria-labelledby="dc-title">
        <h2 id="dc-title">Xavier is not running on this computer</h2>
        <p className="lead">Open Xavier.app. This page reconnects by itself.</p>
      </section>
    </main>
  );
}
