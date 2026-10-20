/** Stateless composite helpers: the caller passes the layer list and canvas dimensions. */

import { makeCanvas } from './placed-layer.js';

/**
 * Union of every visible mask sub-layer across `layers`, rendered as a
 * binary white canvas the size of the document.
 *
 * `lighter` composite = additive — overlapping pixels stay clamped at
 * 255, so wherever any mask painted, the result is solid white.
 * Returns null when no mask layer contributed any pixels (so the caller
 * can early-out cleanly).
 *
 * @param {Array<{masks?: Array<{visible: boolean, canvas: HTMLCanvasElement}>}>} layers
 * @param {number} imgW
 * @param {number} imgH
 * @returns {HTMLCanvasElement|null}
 */
export function buildMergedMaskCanvas(layers, imgW, imgH) {
  if (!imgW || !imgH) return null;
  const out = makeCanvas(imgW, imgH);
  const ctx = out.getContext('2d');
  ctx.globalCompositeOperation = 'lighter';
  let anyMask = false;
  for (const ly of layers) {
    if (!ly.masks || !ly.masks.length) continue;
    for (const mk of ly.masks) {
      if (mk.mode === 'layer') continue;
      if (!mk.visible) continue;
      if (!mk.canvas || !mk.canvas.width || !mk.canvas.height) continue;
      ctx.drawImage(mk.canvas, 0, 0);
      anyMask = true;
    }
  }
  ctx.globalCompositeOperation = 'source-over';
  return anyMask ? out : null;
}


/** Apply visible true layer masks to an already-adjusted layer canvas. */
export function renderWithLayerMasks(source, layer, layerOffset = { x: 0, y: 0 }) {
  const masks = (layer?.masks || []).filter(mask => mask.mode === 'layer' && mask.visible !== false);
  if (!source || masks.length === 0) return source;
  const out = makeCanvas(source.width, source.height);
  const ctx = out.getContext('2d');
  ctx.drawImage(source, 0, 0);
  ctx.globalCompositeOperation = 'destination-in';
  for (const mask of masks) {
    ctx.globalAlpha = Number.isFinite(Number(mask.density))
      ? Math.max(0, Math.min(1, Number(mask.density)))
      : 1;
    const feather = Number.isFinite(Number(mask.feather))
      ? Math.max(0, Math.min(200, Number(mask.feather)))
      : 0;
    ctx.filter = feather > 0 ? `blur(${feather}px)` : 'none';
    if (mask.space === 'document') {
      ctx.drawImage(mask.canvas, -(layerOffset.x || 0), -(layerOffset.y || 0));
    } else {
      const offset = mask.offset && typeof mask.offset === 'object' ? mask.offset : { x: 0, y: 0 };
      ctx.drawImage(mask.canvas, Number(offset.x) || 0, Number(offset.y) || 0);
    }
  }
  ctx.globalAlpha = 1;
  ctx.filter = 'none';
  ctx.globalCompositeOperation = 'source-over';
  return out;
}
