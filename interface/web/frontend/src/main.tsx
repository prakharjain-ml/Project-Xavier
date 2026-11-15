import { StrictMode, useCallback, useEffect, useRef, useState } from "react";
import type { RefObject } from "react";
import { createRoot } from "react-dom/client";
import { connect, sendAction, takeControl } from "./api";
import type { Pointer } from "./api";
import { DriveView } from "./drive";
import { DeviceSetup, Disconnected, ErrorScreen, EyeCalibration, Welcome } from "./screens";
import type { Telemetry } from "./types";
import "./styles.css";

type Act = (type: string, fields?: Record<string, unknown>) => void;

const DRIVE_FLOWS = new Set(["READY", "SELECTING", "NAVIGATING", "PAUSED", "ARRIVED"]);
const LAYOUT_DEBOUNCE_MS = 120;

function useLayoutReports(session: string | null, stage: RefObject<HTMLDivElement>, act: Act, active: boolean): void {
  useEffect(() => {
    if (!session) return;
    let timer: number | undefined;
    const report = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        const r = stage.current?.getBoundingClientRect();
        act("layout", {
          layout: {
            viewport_w: window.innerWidth, viewport_h: window.innerHeight,
            screen_w: window.screen.width, screen_h: window.screen.height,
            dpr: window.devicePixelRatio || 1, fullscreen: document.fullscreenElement != null,
            video: r && r.width > 0 ? [r.left, r.top, r.width, r.height] : null,
          },
        });
      }, LAYOUT_DEBOUNCE_MS);
    };
    report();
    const observer = new ResizeObserver(report);
    if (stage.current) observer.observe(stage.current);
    window.addEventListener("resize", report);
    document.addEventListener("fullscreenchange", report);
    return () => {
      window.clearTimeout(timer);
      observer.disconnect();
      window.removeEventListener("resize", report);
      document.removeEventListener("fullscreenchange", report);
    };
  }, [session, stage, act, active]);
}

function useKeys(t: Telemetry | null, act: Act): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!t || !t.session || !t.you_control) return;
      const target = e.target as HTMLElement;
      // A focused control owns its own keys: SPACE on a button presses that button, never drives the chair.
      if (["INPUT", "SELECT", "TEXTAREA", "BUTTON"].includes(target.tagName) && (e.key === " " || e.key === "Enter")) return;
      const keyMode = t.confirm === "key" || t.confirm === "blink";
      const key = e.key.toLowerCase();
      if (key === "escape" || (keyMode ? key === "s" : key === " ")) {
        e.preventDefault();
        act("estop");
      } else if (keyMode && key === " " && t.flow === "SELECTING") {
        e.preventDefault();
        act("confirm");
      } else if (key === "x") act("cancel_destination");
      else if (key === "c") act("recenter");
      else if (key === "r" && t.flow === "PAUSED") act("rearm");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [t, act]);
}

function TopBar({ t, onFullscreen }: { t: Telemetry | null; onFullscreen: () => void }) {
  return (
    <header className="topbar">
      <div className="brand"><span className="brand-mark" aria-hidden="true" />XAVIER</div>
      <div className="spacer" />
      {t?.session && <span className={`chip ${t.mode === "mock" ? "practice" : "ok"}`}><span className="dot" />{t.mode === "mock" ? "Practice · nothing moves" : "Live cameras"}</span>}
      {t?.session && <span className="chip">Confirm: {t.confirm}</span>}
      {t?.motor && <span className={`chip ${t.motor.stop ? "" : "warn"}`}><span className="dot" />Motors {t.motor.stop ? "stopped" : "moving"} ({t.motor.port})</span>}
      <span className={`chip ${t ? "ok" : "warn"}`}><span className="dot" />{t ? "Connected" : "Disconnected"}</span>
      <button className="btn ghost" style={{ minHeight: 40 }} onClick={onFullscreen}>Full screen</button>
    </header>
  );
}

function App() {
  const [t, setT] = useState<Telemetry | null>(null);
  const live = useRef<Telemetry | null>(null);
  const pointer = useRef<Pointer>(null);
  const stage = useRef<HTMLDivElement>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const move = (e: PointerEvent) => { pointer.current = [e.clientX / window.innerWidth, e.clientY / window.innerHeight]; };
    const leave = () => { pointer.current = null; };
    window.addEventListener("pointermove", move);
    document.addEventListener("pointerleave", leave);
    const stop = connect((next) => { live.current = next; setT(next); }, () => pointer.current);
    return () => {
      stop();
      window.removeEventListener("pointermove", move);
      document.removeEventListener("pointerleave", leave);
    };
  }, []);

  const act = useCallback<Act>(async (type, fields = {}) => {
    if (type === "start_session") setBusy(true);
    const result = await sendAction(type, fields, live.current?.session ?? null);
    setBusy(false);
    if (!result.ok && type !== "layout") setNotice(result.error ?? "Something went wrong");
    else if (result.ok && type !== "layout") setNotice(null);
  }, []);

  const flow = t?.flow;
  const driving = flow !== undefined && DRIVE_FLOWS.has(flow);
  useLayoutReports(t?.session ?? null, stage, act, driving);
  useKeys(t, act);
  const fullscreen = () => {
    const request = document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
    request.catch(() => setNotice("Full screen was refused by the browser"));
  };

  let body;
  if (!t) body = <Disconnected />;
  else if (flow === "IDLE" || flow === "SESSION_ENDED") body = <Welcome act={act} busy={busy} ended={flow === "SESSION_ENDED"} />;
  else if (flow === "DEVICE_SETUP") body = <DeviceSetup t={t} act={act} busy={busy} />;
  else if (flow === "EYE_CALIBRATION" || flow === "EYE_VALIDATION" || flow === "JAW_CALIBRATION") body = <EyeCalibration act={act} />;
  else if (flow === "ERROR") body = <ErrorScreen t={t} act={act} />;
  else body = <DriveView telemetry={t} live={live} stageRef={stage} act={act} />;

  return (
    <div className="app">
      <TopBar t={t} onFullscreen={fullscreen} />
      <div className="main">{body}</div>
      {t && !t.you_control && (
        <div className="watching chip warn" role="status">
          <span className="dot" />This window is only watching.
          <button className="btn ghost" style={{ minHeight: 32 }} onClick={() => takeControl().then((r) => { if (!r.ok) setNotice(r.error ?? ""); })}>Take control</button>
        </div>
      )}
      {t?.mode === "live" && driving && !document.fullscreenElement && (
        <div className="watching chip warn" role="status" style={{ bottom: 64 }}><span className="dot" />Gaze needs full screen. Press "Full screen".</div>
      )}
      {notice && (
        <div className="watching chip warn" role="alert" style={{ bottom: 112 }} onClick={() => setNotice(null)}>
          <span className="dot" />{notice}
        </div>
      )}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
