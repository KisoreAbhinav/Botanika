export const REQUIRED_STABLE_SAMPLES = 3;
export const STABLE_FRAME_DIFFERENCE = 8;
export const NEW_SCENE_DIFFERENCE = 18;

// Reduce a camera frame to a small luminance signature. Comparing this fixed
// size signature is cheap enough to run on a phone and avoids uploading video
// while the operator is moving or reframing.
export function frameSignature(imageData, columns = 24, rows = 18) {
  const width = Number(imageData?.width) || 0;
  const height = Number(imageData?.height) || 0;
  const data = imageData?.data;
  if (!width || !height || !data || data.length < width * height * 4) return null;
  const signature = new Uint8Array(columns * rows);
  for (let row = 0; row < rows; row += 1) {
    const y = Math.min(height - 1, Math.floor(((row + 0.5) * height) / rows));
    for (let column = 0; column < columns; column += 1) {
      const x = Math.min(width - 1, Math.floor(((column + 0.5) * width) / columns));
      const offset = (y * width + x) * 4;
      signature[row * columns + column] = Math.round(
        0.2126 * data[offset] + 0.7152 * data[offset + 1] + 0.0722 * data[offset + 2],
      );
    }
  }
  return signature;
}

export function signatureDifference(left, right) {
  if (!left || !right || left.length !== right.length || left.length === 0) return Infinity;
  let difference = 0;
  for (let index = 0; index < left.length; index += 1) {
    difference += Math.abs(left[index] - right[index]);
  }
  return difference / left.length;
}

export function advanceStability(previous, current, stableChecks, threshold = STABLE_FRAME_DIFFERENCE) {
  if (!current) return { stableChecks: 0, difference: Infinity };
  const difference = signatureDifference(previous, current);
  return {
    stableChecks: difference <= threshold ? Math.max(1, Number(stableChecks) || 0) + 1 : 1,
    difference,
  };
}

export function highestConfidenceMatch(result) {
  if (!result) return null;
  if (result.status === "accepted" && result.common_name) {
    return {
      common_name: result.common_name,
      scientific_name: result.scientific_name,
      confidence: result.confidence,
      accepted: true,
    };
  }
  const suggestions = Array.isArray(result.suggestions) ? result.suggestions : [];
  const best = suggestions.reduce((current, suggestion) => (
    !current || Number(suggestion.confidence) > Number(current.confidence) ? suggestion : current
  ), null);
  return best ? { ...best, accepted: false } : null;
}
