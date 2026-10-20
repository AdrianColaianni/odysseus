/**
 * Pure blur renderers shared by the editor's live-preview popups.
 *
 * Each export matches the `renderer(snap, params, dst)` signature
 * expected by `_applyLiveBlur` in galleryEditor.js — `snap` is the
 * pre-blur snapshot canvas, `params` is the slider values object, and
 * `dst` is the 2D context to draw the final result into. No module
 * state.
 */

import { makeCanvas } from '../placed-layer.js';

/**
 * Gaussian blur with clamp-to-edge sampling.
 *
 * Canvas `filter: blur()` naively blends with TRANSPARENT pixels outside
 * the image which fades the borders out. To match Photoshop's
 * "Edge: Clamp" Gaussian we pad the source onto a larger buffer with
 * the edge pixels stretched into the margin (4 strips + 4 corners),
 * blur the padded buffer, then copy only the original-size centre back.
 *
 * @param {HTMLCanvasElement} snap
 * @param {{ radius: number }} v
 * @param {CanvasRenderingContext2D} dst
 */
export function gaussianBlur(snap, v, dst) {
  if (!v.radius || v.radius <= 0) { dst.drawImage(snap, 0, 0); return; }
  const r = v.radius;
  const w = snap.width, h = snap.height;
  // Margin needs to cover the kernel's effective reach — most
  // engines saturate within ~2× the radius.
  const m = Math.ceil(r * 2 + 4);
  const pad = makeCanvas(w + m * 2, h + m * 2);
  const pctx = pad.getContext('2d');
  pctx.drawImage(snap, m, m);
  // Edge strips: drawImage with src height=1 (or width=1) into a
  // dst region of size `m` stretches the edge pixels into the
  // margin — same effect as clamp-to-edge sampling.
  pctx.drawImage(snap, 0, 0, w, 1, m, 0, w, m);
  pctx.drawImage(snap, 0, h - 1, w, 1, m, m + h, w, m);
  pctx.drawImage(snap, 0, 0, 1, h, 0, m, m, h);
  pctx.drawImage(snap, w - 1, 0, 1, h, m + w, m, m, h);
  // Corners — stretch the corner pixel into an m×m block.
  pctx.drawImage(snap, 0, 0, 1, 1, 0, 0, m, m);
  pctx.drawImage(snap, w - 1, 0, 1, 1, m + w, 0, m, m);
  pctx.drawImage(snap, 0, h - 1, 1, 1, 0, m + h, m, m);
  pctx.drawImage(snap, w - 1, h - 1, 1, 1, m + w, m + h, m, m);
  // Blur the padded buffer and crop the original-size centre back.
  const out = makeCanvas(pad.width, pad.height);
  const octx = out.getContext('2d');
  octx.filter = `blur(${r}px)`;
  octx.drawImage(pad, 0, 0);
  octx.filter = 'none';
  dst.drawImage(out, m, m, w, h, 0, 0, w, h);
}


/**
 * Zoom blur — radial smear from the canvas centre. 16 scaled copies at
 * low alpha approximate a Gaussian zoom blur.
 *
 * @param {HTMLCanvasElement} snap
 * @param {{ strength: number }} v
 * @param {CanvasRenderingContext2D} dst
 */
export function zoomBlur(snap, v, dst) {
  const w = snap.width, h = snap.height;
  const steps = 16;
  dst.drawImage(snap, 0, 0);
  dst.globalAlpha = 0.18;
  for (let s = 1; s <= steps; s++) {
    const t = s / steps;
    const scale = 1 + (v.strength / 200) * t;
    const sw = w * scale, sh = h * scale;
    dst.drawImage(snap, (w - sw) / 2, (h - sh) / 2, sw, sh);
  }
  dst.globalAlpha = 1;
}


