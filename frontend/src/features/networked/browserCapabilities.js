export function cameraAccessMode(scope = globalThis) {
  if (scope.isSecureContext && scope.navigator?.mediaDevices?.getUserMedia) {
    return "stream";
  }
  return "capture-input";
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
