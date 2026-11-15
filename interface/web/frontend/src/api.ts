// The one place that knows where the backend is. Served by the laptop -> same origin. Hosted (Vercel) -> the
// companion on this laptop at 127.0.0.1:8765 (Chrome allows an https page to call loopback; the backend lists the
// hosted origin). Nothing else in the app builds URLs.
import type { Telemetry } from "./types";

const LOCAL_HOSTS = new Set(["127.0.0.1", "localhost"]);
const COMPANION = "http://127.0.0.1:8765";
export const API_BASE = LOCAL_HOSTS.has(window.location.hostname) ? "" : COMPANION;
export const IS_HOSTED = API_BASE !== "";
const WS_BASE = API_BASE
  ? API_BASE.replace(/^http/, "ws")
  : `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`;

export const VIDEO_URL = `${API_BASE}/video/forward.mjpg`;
const BEAT_MS = 100; // heartbeat (and practice pointer) 10x a second; the server stops the chair after 500 ms

function newClientId(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return "tab-" + Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}
export const CLIENT_ID = newClientId(); // one per tab: a second tab is a different (watching) client

export interface ActionResult {
  ok: boolean;
  error?: string;
  session?: string | null;
}

let seq = 0;

export async function sendAction(type: string, fields: Record<string, unknown> = {},
                                 session: string | null = null): Promise<ActionResult> {
  seq += 1;
  try {
    const res = await fetch(`${API_BASE}/api/action`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Xavier-Client": CLIENT_ID },
      body: JSON.stringify({ type, seq, session, ...fields }),
    });
    const body = (await res.json()) as ActionResult;
    return res.ok ? body : { ok: false, error: body.error ?? `HTTP ${res.status}` };
  } catch (error: unknown) {
    return { ok: false, error: error instanceof Error ? error.message : "Backend unreachable" };
  }
}

export async function takeControl(): Promise<ActionResult> {
  try {
    const res = await fetch(`${API_BASE}/api/take_control`, {
      method: "POST", headers: { "X-Xavier-Client": CLIENT_ID },
    });
    return (await res.json()) as ActionResult;
  } catch {
    return { ok: false, error: "Backend unreachable" };
  }
}

export type Pointer = [number, number] | null;

/** Live connection: telemetry in, heartbeat (+ pointer) out. Reconnects by itself; never resumes motion. */
export function connect(onTelemetry: (t: Telemetry | null) => void, pointer: () => Pointer): () => void {
  let socket: WebSocket | null = null;
  let beat: number | undefined;
  let retry: number | undefined;
  let closed = false;

  const open = () => {
    socket = new WebSocket(`${WS_BASE}/ws?client=${CLIENT_ID}`);
    socket.onmessage = (event) => onTelemetry(JSON.parse(event.data as string) as Telemetry);
    socket.onopen = () => {
      beat = window.setInterval(() => {
        if (socket?.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({ type: "beat", pointer: pointer() }));
        }
      }, BEAT_MS);
    };
    socket.onclose = () => {
      window.clearInterval(beat);
      onTelemetry(null); // the page shows "Backend disconnected" at once
      if (!closed) retry = window.setTimeout(open, 1000);
    };
  };
  open();
  return () => {
    closed = true;
    window.clearInterval(beat);
    window.clearTimeout(retry);
    socket?.close();
  };
}
