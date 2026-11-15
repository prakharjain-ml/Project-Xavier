// Mirror of interface/web/telemetry.py snapshot(). Keep the two in step.
export type Flow =
  | "IDLE" | "DEVICE_SETUP" | "EYE_CALIBRATION" | "EYE_VALIDATION" | "JAW_CALIBRATION" | "READY"
  | "SELECTING" | "NAVIGATING" | "PAUSED" | "ARRIVED" | "ERROR" | "SESSION_ENDED";

export type ConfirmMode = "dwell" | "key" | "blink" | "jaw";

export interface SceneObject {
  id: number;
  label: string;
  box: [number, number, number, number]; // x1, y1, x2, y2 in source-frame pixels
  distance_m: number | null;             // approximate (from box height)
  candidate: boolean;
  confirmed: boolean;
  progress: number;                      // 0..1 confirm readiness
  remembered: boolean;                   // out of sight: last known box (not a fresh detection)
}

export interface Device {
  status: string;
  detail: string;
}

export interface UiEvent {
  t: number;
  text: string;
  tone: "info" | "success" | "warn";
}

export interface Telemetry {
  flow: Flow;
  session: string | null;
  mode: "mock" | "live";
  confirm: ConfirmMode;
  you_control: boolean;
  controller_fresh: boolean;
  calibrated: boolean;
  stop_reason: string | null;
  error: string | null;
  arrived_at: string | null;
  frame: { t: number; w: number; h: number; age_s: number } | null;
  objects: SceneObject[];
  gaze: { point: [number, number] | null; age_s: number | null; on: number | null };
  route: { status: "none" | "planning" | "no_route" | "ready" | "held"; points_m: [number, number][]; length_m?: number };
  obstacles_m: [number, number][];
  motor: { left: number; right: number; stop: boolean; port: string } | null;
  devices: Record<string, Device>;
  jaw: { prompt: string | null; level: number | null };
  drive_mode: "auto" | "manual";
  arrow: "FWD" | "BACK" | "LEFT" | "RIGHT" | null;
  arrow_regions: Record<string, [number, number, number, number]>;
  ready?: { phone_camera?: boolean; headset_wifi?: boolean; eye_calibration?: boolean; chair?: boolean };
  events: UiEvent[];
  diag: { tick_ms: number; note: string; encode_ms?: number };
}
