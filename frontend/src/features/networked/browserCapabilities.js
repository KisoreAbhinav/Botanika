export function cameraAccessMode(scope = globalThis) {
  if (scope.isSecureContext && scope.navigator?.mediaDevices?.getUserMedia) {
    return "stream";
  }
  return "capture-input";
}

/**
 * Attach a browser-owned stream after its video element has mounted. Mobile
 * browsers may resolve getUserMedia before a conditional video element exists.
 */
export function attachCameraStream(video, stream) {
  if (!video || !stream) return false;
  video.srcObject = stream;
  const playback = video.play?.();
  if (playback && typeof playback.catch === "function") playback.catch(() => {});
  return true;
}

export function canRequestPosition(scope = globalThis) {
  return Boolean(scope.isSecureContext && scope.navigator?.geolocation);
}

export function positionPayload(position) {
  const accuracy = Number(position?.coords?.accuracy);
  const latitude = Number(position?.coords?.latitude);
  const longitude = Number(position?.coords?.longitude);
  if (
    !Number.isFinite(accuracy)
    || accuracy < 0
    || accuracy > 1000
    || !Number.isFinite(latitude)
    || latitude < -90
    || latitude > 90
    || !Number.isFinite(longitude)
    || longitude < -180
    || longitude > 180
  ) {
    return null;
  }
  return {
    latitude,
    longitude,
    accuracy_m: accuracy,
    timestamp: Number(position.timestamp) / 1000,
    source: "paired-browser-geolocation",
  };
}
