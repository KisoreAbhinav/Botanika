// Bounded geolocation sampler for live weed frames. A valid fix is reused for
// a short window so every positive frame can carry the same device location;
// refreshes are throttled and concurrent calls share one promise.

export const DEFAULT_LOCATION_REFRESH_MS = 10_000;
export const DEFAULT_LOCATION_MAX_AGE_MS = 30_000;

export function createLocationSampler(
  getPosition,
  {
    clock = () => Date.now(),
    refreshIntervalMs = DEFAULT_LOCATION_REFRESH_MS,
    maxAgeMs = DEFAULT_LOCATION_MAX_AGE_MS,
  } = {},
) {
  if (typeof getPosition !== "function") throw new TypeError("getPosition must be a function");
  const state = {
    attemptedAt: Number.NEGATIVE_INFINITY,
    value: null,
    valueAt: Number.NEGATIVE_INFINITY,
    pending: null,
  };
  return function sample() {
    const now = Number(clock());
    const cached = state.value && now - state.valueAt <= maxAgeMs ? state.value : null;
    if (!cached) {
      state.value = null;
      state.valueAt = Number.NEGATIVE_INFINITY;
    }
    if (state.pending) return state.pending;
    if (now - state.attemptedAt < refreshIntervalMs) return cached;
    state.attemptedAt = now;
    state.pending = Promise.resolve()
      .then(() => getPosition())
      .then((value) => {
        const refreshedAt = Number(clock());
        if (value) {
          state.value = value;
          state.valueAt = refreshedAt;
        } else if (refreshedAt - state.valueAt > maxAgeMs) {
          state.value = null;
          state.valueAt = Number.NEGATIVE_INFINITY;
        }
        return state.value && refreshedAt - state.valueAt <= maxAgeMs ? state.value : null;
      })
      .finally(() => {
        state.pending = null;
      });
    return state.pending;
  };
}
