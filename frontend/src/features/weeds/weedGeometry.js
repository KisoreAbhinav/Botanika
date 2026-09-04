// Geometry for an object-fit: contain image and an overlay that must stay
// attached to the analyzed still at kiosk and phone aspect ratios.

export function containedImageRect(containerWidth, containerHeight, imageWidth, imageHeight) {
  const width = finitePositive(containerWidth);
  const height = finitePositive(containerHeight);
  const sourceWidth = finitePositive(imageWidth);
  const sourceHeight = finitePositive(imageHeight);
  if (!width || !height || !sourceWidth || !sourceHeight) {
    return { width: 0, height: 0, offsetX: 0, offsetY: 0, scale: 0 };
  }
  const scale = Math.min(width / sourceWidth, height / sourceHeight);
  const renderedWidth = sourceWidth * scale;
  const renderedHeight = sourceHeight * scale;
  return {
    width: renderedWidth,
    height: renderedHeight,
    offsetX: (width - renderedWidth) / 2,
    offsetY: (height - renderedHeight) / 2,
    scale,
  };
}
export function containedBox(box, containerWidth, containerHeight, imageWidth, imageHeight) {
  const rect = containedImageRect(containerWidth, containerHeight, imageWidth, imageHeight);
  if (!rect.scale) return { left: 0, top: 0, width: 0, height: 0 };
  const x1 = finite(box?.x1);
  const y1 = finite(box?.y1);
  const x2 = finite(box?.x2);
  const y2 = finite(box?.y2);
  return {
    left: rect.offsetX + x1 * rect.scale,
    top: rect.offsetY + y1 * rect.scale,
    width: Math.max(0, (x2 - x1) * rect.scale),
    height: Math.max(0, (y2 - y1) * rect.scale),
  };
}

function finitePositive(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : 0;
}

function finite(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}
