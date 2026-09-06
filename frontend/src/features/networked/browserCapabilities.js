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
export function attachCameraStream(video, stream, onPlaybackError) {
  if (!video || !stream) return false;
  // Set these properties before assigning srcObject. Some mobile Chromium
  // builds do not consistently honor React's initial media attributes when a
  // conditional video element mounts after getUserMedia resolves.
  video.autoplay = true;
  video.muted = true;
  video.playsInline = true;
  if (video.srcObject !== stream) video.srcObject = stream;
  let playback;
  try {
    playback = video.play?.();
  } catch (error) {
    if (isCurrentStream(video, stream) && typeof onPlaybackError === "function") onPlaybackError(error);
    return false;
  }
  if (playback && typeof playback.catch === "function") {
    playback.catch((error) => {
      if (isCurrentStream(video, stream) && typeof onPlaybackError === "function") onPlaybackError(error);
    });
  }
  return true;
}

function isCurrentStream(video, stream) {
  // A pending crop unmounts the video while its play promise may still be
  // settling. Ignore late failures from that detached element.
  if (video.isConnected === false) return false;
  if (video.srcObject !== stream) return false;
  const tracks = stream.getTracks?.();
  return !Array.isArray(tracks) || tracks.some((track) => track.readyState !== "ended");
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
