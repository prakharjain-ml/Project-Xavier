// Same contract as interface/web/coords.py: the camera picture is drawn with object-fit: contain, so the overlay
// maps source-frame pixels into the letterboxed content rectangle, never into the bars.
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export function containRect(box: Rect, frameW: number, frameH: number): Rect {
  if (frameW <= 0 || frameH <= 0 || box.w <= 0 || box.h <= 0) return { x: box.x, y: box.y, w: 0, h: 0 };
  const scale = Math.min(box.w / frameW, box.h / frameH);
  const w = frameW * scale;
  const h = frameH * scale;
  return { x: box.x + (box.w - w) / 2, y: box.y + (box.h - h) / 2, w, h };
}

/** Source-frame pixel -> position inside the element (CSS px). */
export function frameToElement(px: number, py: number, content: Rect, frameW: number, frameH: number): [number, number] {
  return [content.x + (px / frameW) * content.w, content.y + (py / frameH) * content.h];
}
