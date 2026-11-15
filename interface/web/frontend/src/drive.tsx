// The main view while choosing and driving: the forward camera with a canvas overlay (objects, confirm progress,
// gaze), and a side panel (destination, route, keys, STOP). Drawing runs in requestAnimationFrame from the newest
// telemetry in a ref, so gaze updates never re-render React.
import { useEffect, useRef } from "react";
import type { MutableRefObject, RefObject } from "react";
import { VIDEO_URL } from "./api";
import { containRect, frameToElement } from "./coords";
import type { Rect } from "./coords";
import type { SceneObject, Telemetry } from "./types";

const CYAN = "#22d3ee";
const GREEN = "#10b981";
const PALE = "rgba(118, 226, 238, 0.75)";
const INK = "rgba(11, 15, 20, 0.9)";

interface DriveProps {
  telemetry: Telemetry;
  live: MutableRefObject<Telemetry | null>;
  stageRef: RefObject<HTMLDivElement>;
  act: (type: string, fields?: Record<string, unknown>) => void;
}

function labelFor(o: SceneObject): string {
  const name = o.label[0].toUpperCase() + o.label.slice(1);
  const dist = o.distance_m != null ? ` · ≈${o.distance_m.toFixed(1)} m` : "";
  return `${name}${dist}${o.remembered ? " · last seen" : ""}`;
}

function drawObject(ctx: CanvasRenderingContext2D, o: SceneObject, t: Telemetry, content: Rect): void {
  if (!t.frame) return;
  const [x1, y1] = frameToElement(o.box[0], o.box[1], content, t.frame.w, t.frame.h);
  const [x2, y2] = frameToElement(o.box[2], o.box[3], content, t.frame.w, t.frame.h);
  const color = o.confirmed ? GREEN : o.candidate ? CYAN : PALE;
  ctx.save();
  if (o.confirmed || o.candidate) {
    ctx.fillStyle = o.confirmed ? "rgba(16, 185, 129, 0.18)" : "rgba(34, 211, 238, 0.10)";
    ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
  }
  ctx.strokeStyle = color;
  ctx.lineWidth = o.confirmed || o.candidate ? 3 : 1.5;
  if (o.remembered) ctx.setLineDash([8, 6]); // last known place, not a fresh detection
  const arm = Math.min(28, Math.max(10, (x2 - x1) * 0.18));
  ctx.beginPath(); // corner brackets: lighter than a full box over the video
  const corners: [number, number, number, number][] = [[x1, y1, 1, 1], [x2, y1, -1, 1], [x1, y2, 1, -1], [x2, y2, -1, -1]];
  for (const [cx, cy, dx, dy] of corners) {
    ctx.moveTo(cx + dx * arm, cy);
    ctx.lineTo(cx, cy);
    ctx.lineTo(cx, cy + dy * arm);
  }
  ctx.stroke();
  ctx.setLineDash([]);
  const label = labelFor(o);
  ctx.font = "600 15px -apple-system, BlinkMacSystemFont, sans-serif";
  const lead = o.confirmed ? 14 : 0;
  const w = ctx.measureText(label).width + 28 + lead;
  const px = Math.min(Math.max(x1, 6), ctx.canvas.clientWidth - w - 6);
  const py = Math.max(y1 - 44, 6);
  ctx.fillStyle = INK;
  ctx.strokeStyle = o.confirmed ? GREEN : "rgba(52, 66, 88, 1)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.roundRect(px, py, w, 34, 17);
  ctx.fill();
  ctx.stroke();
  if (o.confirmed) {
    ctx.fillStyle = GREEN;
    ctx.beginPath();
    ctx.arc(px + 18, py + 17, 5, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.fillStyle = "#e6edf3";
  ctx.fillText(label, px + 14 + lead, py + 22);
  if (o.candidate && !o.confirmed && o.progress > 0) { // confirm readiness ring at the object's centre
    const cx = (x1 + x2) / 2;
    const cy = (y1 + y2) / 2;
    ctx.lineWidth = 6;
    ctx.strokeStyle = "rgba(255,255,255,0.18)";
    ctx.beginPath();
    ctx.arc(cx, cy, 26, 0, Math.PI * 2);
    ctx.stroke();
    ctx.strokeStyle = CYAN;
    ctx.beginPath();
    ctx.arc(cx, cy, 26, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * o.progress);
    ctx.stroke();
  }
  ctx.restore();
}

function drawArrows(ctx: CanvasRenderingContext2D, t: Telemetry, content: Rect): void {
  // The same areas the backend tests the gaze against (vision/manual_arrows.py ARROW_REGIONS).
  for (const [name, [x1, y1, x2, y2]] of Object.entries(t.arrow_regions)) {
    const active = t.arrow === name;
    const cx = content.x + ((x1 + x2) / 2) * content.w;
    const cy = content.y + ((y1 + y2) / 2) * content.h;
    const half = Math.min((x2 - x1) * content.w, (y2 - y1) * content.h) * 0.32;
    const pts: Record<string, [number, number][]> = {
      FWD: [[cx, cy - half], [cx - half, cy + half], [cx + half, cy + half]],
      BACK: [[cx, cy + half], [cx - half, cy - half], [cx + half, cy - half]],
      LEFT: [[cx - half, cy], [cx + half, cy - half], [cx + half, cy + half]],
      RIGHT: [[cx + half, cy], [cx - half, cy - half], [cx - half, cy + half]],
    };
    ctx.save();
    ctx.fillStyle = active ? "rgba(34, 211, 238, 0.22)" : "rgba(11, 15, 20, 0.35)";
    ctx.strokeStyle = active ? CYAN : "rgba(230, 237, 243, 0.25)";
    ctx.lineWidth = active ? 2 : 1;
    ctx.beginPath();
    ctx.roundRect(content.x + x1 * content.w + 6, content.y + y1 * content.h + 6,
                  (x2 - x1) * content.w - 12, (y2 - y1) * content.h - 12, 18);
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = active ? CYAN : "rgba(230, 237, 243, 0.8)";
    ctx.beginPath();
    pts[name].forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }
}

function useOverlay(canvasRef: RefObject<HTMLCanvasElement>, live: MutableRefObject<Telemetry | null>): void {
  useEffect(() => {
    let frame = 0;
    const draw = () => {
      frame = requestAnimationFrame(draw);
      const canvas = canvasRef.current;
      const t = live.current;
      if (!canvas || !t) return;
      const dpr = window.devicePixelRatio || 1;
      const { clientWidth: w, clientHeight: h } = canvas;
      if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
        canvas.width = Math.round(w * dpr);
        canvas.height = Math.round(h * dpr);
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      if (!t.frame) return;
      const content = containRect({ x: 0, y: 0, w, h }, t.frame.w, t.frame.h);
      if (t.drive_mode === "manual") {
        drawArrows(ctx, t, content);
      } else {
        const shown = t.objects.some((o) => o.confirmed) ? t.objects.filter((o) => o.confirmed) : t.objects;
        for (const o of shown) drawObject(ctx, o, t, content);
      }
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [canvasRef, live]);
}

const ROUTE_TEXT: Record<Telemetry["route"]["status"], string | null> = {
  none: null,
  planning: "Planning a route…",
  no_route: "No safe route from here",
  ready: null,
  held: "Destination out of sight",
};

function Overlays({ t, act }: { t: Telemetry; act: DriveProps["act"] }) {
  if (t.flow === "PAUSED") {
    return (
      <div className="overlay-card" role="alertdialog" aria-labelledby="paused-title">
        <div className="card center">
          <h2 id="paused-title">{t.stop_reason ?? "Stopped"}</h2>
          <button className="btn warn lg" onClick={() => act("rearm")} autoFocus>Re-arm</button>
        </div>
      </div>
    );
  }
  if (t.flow === "ARRIVED") {
    return (
      <div className="overlay-card" role="dialog" aria-labelledby="arrived-title">
        <div className="card center">
          <h2 id="arrived-title">Arrived at {t.arrived_at}</h2>
          <button className="btn primary lg" onClick={() => act("choose_again")} autoFocus>Choose another</button>
        </div>
      </div>
    );
  }
  return null;
}

const ARROW_TEXT: Record<string, string> = { FWD: "Forward", BACK: "Backward", LEFT: "Rotating left", RIGHT: "Rotating right" };

function JawMeter({ level }: { level: number | null }) {
  // Live muscle level from the headset as a share of this rider's calibrated threshold (1.0 = a clench).
  const share = level == null ? 0 : Math.min(level, 1.5) / 1.5;
  const over = level != null && level >= 1;
  return (
    <section className="panel jaw" aria-label="Jaw clench level">
      <div className="jaw-head">
        <span className="eyebrow">Jaw</span>
        <span className={over ? "jaw-state on" : "jaw-state"}>{level == null ? "No signal" : over ? "Clench" : "Relaxed"}</span>
      </div>
      <div className="jaw-bar">
        <i style={{ transform: `scaleX(${share})` }} className={over ? "on" : ""} />
        <b style={{ left: `${(1 / 1.5) * 100}%` }} aria-hidden="true" />
      </div>
    </section>
  );
}

export function DriveView({ telemetry: t, live, stageRef, act }: DriveProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useOverlay(canvasRef, live);
  const chosen = t.objects.find((o) => o.confirmed);
  const stale = t.frame && t.frame.age_s > 1 ? `Camera picture is ${t.frame.age_s.toFixed(1)} s old` : null;
  const noGaze = t.flow === "SELECTING" && !t.gaze.point ? "No gaze" : null;
  const route = ROUTE_TEXT[t.route.status];
  return (
    <div className="drive">
      <div className="stage" ref={stageRef}>
        <img src={VIDEO_URL} alt="Room camera" />
        <canvas ref={canvasRef} aria-hidden="true" />
        {(stale || noGaze) && <div className="banner warn" role="status">{stale ?? noGaze}</div>}
        <Overlays t={t} act={act} />
      </div>
      <aside className="side" aria-label="Drive">
        <div className="segmented mode-switch" role="group" aria-label="Drive mode">
          <button aria-pressed={t.drive_mode === "auto"} onClick={() => act("set_drive_mode", { drive_mode: "auto" })}>Automatic</button>
          <button aria-pressed={t.drive_mode === "manual"} onClick={() => act("set_drive_mode", { drive_mode: "manual" })}>Manual</button>
        </div>
        {t.drive_mode === "auto" ? (
          <section className="panel dest-panel" aria-live="polite">
            <div className="eyebrow">{chosen ? "Driving to" : "Destination"}</div>
            <div className="dest">{chosen ? chosen.label[0].toUpperCase() + chosen.label.slice(1) : "Look, then clench"}</div>
            {chosen && chosen.distance_m != null && <div className="muted">≈ {chosen.distance_m.toFixed(1)} m</div>}
            {chosen && route && <div className="warn-text">{route}</div>}
            {chosen && <button className="btn ghost" onClick={() => act("cancel_destination")}>Cancel</button>}
          </section>
        ) : (
          <section className="panel dest-panel" aria-live="polite">
            <div className="eyebrow">Manual</div>
            <div className="dest">{t.arrow ? ARROW_TEXT[t.arrow] : "Look at an arrow"}</div>
          </section>
        )}
        <JawMeter level={t.jaw.level} />
        <button className="stop" onClick={() => act("estop")} aria-label="Emergency stop">STOP</button>
      </aside>
    </div>
  );
}
