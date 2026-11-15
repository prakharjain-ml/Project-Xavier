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
      const shown = t.objects.some((o) => o.confirmed) ? t.objects.filter((o) => o.confirmed) : t.objects;
      for (const o of shown) drawObject(ctx, o, t, content);
      const g = t.gaze.point;
      if (g && t.mode === "mock") { // practice: show where the "gaze" (mouse) is; live gaze is not drawn (it jitters)
        const rect = canvas.getBoundingClientRect();
        ctx.strokeStyle = CYAN;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(g[0] * window.innerWidth - rect.left, g[1] * window.innerHeight - rect.top, 12, 0, Math.PI * 2);
        ctx.stroke();
      }
    };
    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [canvasRef, live]);
}

function RouteMap({ t }: { t: Telemetry }) {
  // Top view in metres: chair at the bottom centre, forward = up. Obstacles = what the planner steers around.
  const size = 280;
  const pts = t.route.points_m;
  const extent = Math.max(2, ...pts.map(([x, y]) => Math.max(x, Math.abs(y) * 2)), ...t.obstacles_m.map(([x]) => x));
  const scale = (size - 30) / extent;
  const toXY = ([x, y]: [number, number]): [number, number] => [size / 2 - y * scale, size - 18 - x * scale];
  const line = [[0, 0] as [number, number], ...pts].map((p) => toXY(p).join(",")).join(" ");
  return (
    <svg viewBox={`0 0 ${size} ${size}`} width="100%" role="img" aria-label="Planned route seen from above">
      <rect x="0" y="0" width={size} height={size} rx="12" fill="#121821" />
      {t.obstacles_m.map((p, i) => {
        const [cx, cy] = toXY(p);
        return <circle key={i} cx={cx} cy={cy} r="3" fill="#5c687a" />;
      })}
      {pts.length > 0 && (
        <polyline points={line} fill="none" stroke={t.route.status === "held" ? "#f59e0b" : "#22d3ee"} strokeWidth="3"
                  strokeDasharray={t.route.status === "held" ? "6 5" : undefined} strokeLinecap="round" />
      )}
      <polygon points={`${size / 2},${size - 26} ${size / 2 - 8},${size - 10} ${size / 2 + 8},${size - 10}`} fill="#e6edf3" />
    </svg>
  );
}

const ROUTE_TEXT: Record<Telemetry["route"]["status"], string> = {
  none: "No destination yet",
  planning: "Planning a route…",
  no_route: "No safe route found from here",
  ready: "Route ready",
  held: "Destination out of sight: following the last route",
};

const HOW: Record<Telemetry["confirm"], string> = {
  dwell: "Look at it for 1.5 s", key: "Look at it, then press SPACE", jaw: "Look at it, then clench",
  blink: "Look at it, then blink twice",
};

function Overlays({ t, act }: { t: Telemetry; act: DriveProps["act"] }) {
  if (t.flow === "PAUSED") {
    return (
      <div className="overlay-card" role="alertdialog" aria-labelledby="paused-title">
        <div className="card">
          <div className="eyebrow">Chair stopped</div>
          <h2 id="paused-title">{t.stop_reason ?? "Stopped"}</h2>
          <p className="lead">Nothing moves until you re-arm and choose a destination again.</p>
          <button className="btn warn lg" onClick={() => act("rearm")} autoFocus>Re-arm</button>
        </div>
      </div>
    );
  }
  if (t.flow === "ARRIVED") {
    return (
      <div className="overlay-card" role="dialog" aria-labelledby="arrived-title">
        <div className="card">
          <div className="eyebrow">Arrived</div>
          <h2 id="arrived-title">{t.arrived_at ?? "Destination reached"}</h2>
          <p className="lead">The chair has stopped.</p>
          <button className="btn primary lg" onClick={() => act("choose_again")} autoFocus>Choose another destination</button>
        </div>
      </div>
    );
  }
  return null;
}

export function DriveView({ telemetry: t, live, stageRef, act }: DriveProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useOverlay(canvasRef, live);
  const chosen = t.objects.find((o) => o.confirmed);
  const keyMode = t.confirm === "key" || t.confirm === "blink";
  const stale = t.frame && t.frame.age_s > 1 ? `Camera picture is ${t.frame.age_s.toFixed(1)} s old` : null;
  const banner = t.flow === "NAVIGATING" && chosen ? `Driving to ${chosen.label}` :
    t.flow === "SELECTING" ? (t.gaze.point ? `${HOW[t.confirm]} to choose` : "No gaze: face not seen or eyes closed") : null;
  return (
    <div className="drive">
      <div className="stage" ref={stageRef}>
        <img src={VIDEO_URL} alt="Forward camera" />
        <canvas ref={canvasRef} aria-hidden="true" />
        {(stale || banner) && <div className={`banner ${stale || !t.gaze.point ? "warn" : ""}`} role="status">{stale ?? banner}</div>}
        <Overlays t={t} act={act} />
      </div>
      <aside className="side" aria-label="Drive status">
        <section className="panel" aria-live="polite">
          <h3>Destination</h3>
          <div className="dest">{chosen ? chosen.label[0].toUpperCase() + chosen.label.slice(1) : "None"}</div>
          <div className="muted">{chosen ? (chosen.distance_m != null ? `About ${chosen.distance_m.toFixed(1)} m away (estimate)` : "Distance unknown") : `${HOW[t.confirm]}.`}</div>
          {chosen && <button className="btn ghost" style={{ marginTop: 12 }} onClick={() => act("cancel_destination")}>Cancel destination</button>}
        </section>
        <section className="panel">
          <h3>Route</h3>
          <div className={t.route.status === "no_route" || t.route.status === "held" ? "warn-text" : "muted"}>
            {ROUTE_TEXT[t.route.status]}{t.route.length_m ? ` · ${t.route.length_m.toFixed(1)} m` : ""}
          </div>
          <RouteMap t={t} />
          <div className="note">Floor the camera cannot see is assumed open. The chair's ultrasonic stop is the backstop.</div>
        </section>
        <section className="panel">
          <h3>Keys</h3>
          <div className="keys">
            {keyMode && <><span className="kbd">SPACE</span><span>Confirm</span></>}
            <span className="kbd">{keyMode ? "S" : "SPACE"}</span><span>Emergency stop (or Esc)</span>
            <span className="kbd">X</span><span>Cancel destination</span>
            <span className="kbd">C</span><span>Re-centre gaze (look at the middle)</span>
            <span className="kbd">R</span><span>Re-arm after a stop</span>
          </div>
          {keyMode && t.flow === "SELECTING" && <button className="btn primary" style={{ marginTop: 12, width: "100%" }} onClick={() => act("confirm")}>Confirm the highlighted object</button>}
        </section>
        <section className="panel">
          <h3>Activity</h3>
          <ul className="events">{t.events.slice(-5).reverse().map((e) => <li key={`${e.t}-${e.text}`} className={e.tone}>{e.text}</li>)}</ul>
        </section>
        <details className="panel diag">
          <summary>Diagnostics</summary>
          <div>frame age {t.frame?.age_s.toFixed(2) ?? "-"} s · gaze age {t.gaze.age_s?.toFixed(2) ?? "-"} s</div>
          <div>tick {t.diag.tick_ms} ms · jpeg {t.diag.encode_ms ?? "-"} ms</div>
          <div>motor {t.motor ? (t.motor.stop ? "STOP" : `${t.motor.left}, ${t.motor.right}`) : "-"} ({t.motor?.port})</div>
          <div>{t.diag.note}</div>
        </details>
        <button className="stop" onClick={() => act("estop")} aria-label="Emergency stop">STOP</button>
      </aside>
    </div>
  );
}
