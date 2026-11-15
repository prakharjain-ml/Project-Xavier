// Setup-side screens: welcome, device setup, eye calibration (live), error, disconnected.
import { useState } from "react";
import { IS_HOSTED } from "./api";
import type { ConfirmMode, Telemetry } from "./types";

type Act = (type: string, fields?: Record<string, unknown>) => void;

const MODES: { key: ConfirmMode; title: string; text: string }[] = [
  { key: "dwell", title: "Look", text: "Hold your gaze 1.5 s" },
  { key: "jaw", title: "Jaw clench", text: "Look, then clench" },
  { key: "blink", title: "Blink twice", text: "Look, then blink" },
  { key: "key", title: "Keyboard", text: "Look, then SPACE" },
];

export function Welcome({ act, busy, ended }: { act: Act; busy: boolean; ended: boolean }) {
  const [confirm, setConfirm] = useState<ConfirmMode>("dwell");
  const [eye, setEye] = useState(1);
  const [forward, setForward] = useState(0);
  const sameCamera = eye === forward;
  const start = () => act("start_session", { mode: "live", confirm, eye_camera: eye, forward_camera: forward });
  return (
    <main className="page">
      <section className="card" aria-labelledby="welcome-title">
        <div className="eyebrow">{ended ? "Session ended · everything stopped" : "Assistive navigation"}</div>
        <h1 id="welcome-title">Drive where you look.</h1>
        <p className="lead">Look at a place in the room, confirm it, and Xavier plans a route and drives there.
          Stop is always one key or one click away.</p>
        <p className="note">Requires your Pixel in USB webcam mode for the room view and the Mac webcam
          for eye tracking. Missing cameras cannot be replaced with simulated inputs. Motor output currently
          goes to a test port; real camera input does not mean the wheels are connected.</p>
        <div className="eyebrow" style={{ marginTop: 24 }}>Confirm a destination by</div>
        <div className="modes" role="group" aria-label="Confirm method">
          {MODES.map((m) => (
            <button key={m.key} className="mode" aria-pressed={confirm === m.key} onClick={() => setConfirm(m.key)}>
              <b>{m.title}</b><span>{m.text}</span>
            </button>
          ))}
        </div>
        {(
          <details className="adv" open>
            <summary>Cameras</summary>
            <div className="row" style={{ marginTop: 12 }}>
              <label className="field">Mac webcam (eye tracking)
                <input type="number" min={0} max={16} value={eye} onChange={(e) => setEye(Number(e.target.value))} />
              </label>
              <label className="field">Pixel webcam (room view)
                <input type="number" min={0} max={16} value={forward} onChange={(e) => setForward(Number(e.target.value))} />
              </label>
            </div>
            {sameCamera && <p className="warn-text">The eye and forward cameras must be different.</p>}
          </details>
        )}
        <div className="row" style={{ marginTop: 28 }}>
          <button className="btn primary lg" disabled={busy || sameCamera} onClick={start}>
            {busy ? "Starting…" : "Start session"}
          </button>
        </div>
        {IS_HOSTED && <p className="note">This page talks to the Xavier companion running on this computer. Video stays on this computer.</p>}
      </section>
    </main>
  );
}

const DEVICE_NAMES: Record<string, string> = {
  forward_camera: "Forward camera", eye_camera: "Eye camera", headset: "Headset", chair: "Chair controller",
};
const STATUS_TEXT: Record<string, string> = {
  streaming: "Streaming", opening: "Opening…", no_frames: "No fresh frames", error: "Error", mock: "Simulated",
  not_used: "Not used", unknown: "Not checked",
};

function statusClass(status: string): string {
  if (status === "streaming" || status === "mock") return "ok";
  if (status === "error" || status === "no_frames") return "warn";
  return "";
}

export function DeviceSetup({ t, act, busy }: { t: Telemetry; act: Act; busy: boolean }) {
  return (
    <main className="page">
      <section className="card" aria-labelledby="setup-title">
        <div className="eyebrow">Step 1 · Devices</div>
        <h2 id="setup-title">Check your devices</h2>
        <div className="devices">
          {Object.entries(t.devices).map(([key, d]) => (
            <div key={key} className="device">
              <span className={`chip ${statusClass(d.status)}`}><span className="dot" />{STATUS_TEXT[d.status] ?? d.status}</span>
              <b style={{ marginTop: 10 }}>{DEVICE_NAMES[key] ?? key}</b>
              <small>{d.detail}</small>
            </div>
          ))}
        </div>
        <div className="row">
          <button className="btn primary lg" disabled={busy} onClick={() => act("continue")} autoFocus>Continue</button>
          <button className="btn ghost" onClick={() => act("end_session")}>End session</button>
        </div>
      </section>
    </main>
  );
}

export function EyeCalibration({ act }: { act: Act }) {
  return (
    <main className="page">
      <section className="card" aria-labelledby="cal-title">
        <div className="eyebrow">Step 2 · Eyes</div>
        <h2 id="cal-title">Eye calibration needed</h2>
        <p className="lead">The screen changed since the last calibration, or there is none. In-browser calibration is
          not built yet: calibrate once with the desktop tool, then start a new session.</p>
        <button className="btn ghost" onClick={() => act("end_session")}>End session</button>
      </section>
    </main>
  );
}

export function ErrorScreen({ t, act }: { t: Telemetry; act: Act }) {
  return (
    <main className="page">
      <section className="card" role="alert" aria-labelledby="err-title">
        <div className="eyebrow">Something stopped</div>
        <h2 id="err-title">The chair was stopped</h2>
        <p className="lead">{t.error}</p>
        <button className="btn primary lg" onClick={() => act("end_session")} autoFocus>End session and start again</button>
      </section>
    </main>
  );
}

export function Disconnected() {
  return (
    <main className="page">
      <section className="card" role="alert" aria-labelledby="dc-title">
        <div className="eyebrow">No connection</div>
        <h2 id="dc-title">Can't reach the Xavier companion</h2>
        <p className="lead">{IS_HOSTED
          ? "Start Xavier on this computer (open Xavier.app). This page reconnects by itself."
          : "The local server stopped. Start Xavier again; this page reconnects by itself."}</p>
        <p className="note">If the chair was moving, it has stopped: it stops on its own when this page goes quiet.</p>
      </section>
    </main>
  );
}
