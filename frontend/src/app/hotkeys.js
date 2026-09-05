/**
 * Keyboard navigation primitives for the kiosk shell.
 *
 * Keep this module DOM-light so the guard can be tested without rendering the
 * whole application. Kiosk shortcuts must never steal text-entry, select
 * controls, contenteditable regions, or an open dialog.
 */

export const APP_SHORTCUTS = Object.freeze({
  "1": "scan",
  "2": "library",
  "3": "weeds",
  a: "ask",
  h: "home",
  escape: "home",
  f1: "help",
});

// Page controls advertise their own shortcut with data-hotkey.  The global
// keyboard listener activates only a control that is currently rendered, so
// a scan shortcut cannot accidentally trigger an action on another screen.
// Values are kept here as the single source of truth for button labels and
// the help panel.
export const CONTROL_SHORTCUTS = Object.freeze({
  manualCapture: "Space",
  localImage: "L",
  captureFromImage: "C",
  clearImage: "X",
  saveToLibrary: "S",
  retake: "R",
  anotherAngle: "G",
  cancelScan: "Escape",
  chooseWeedFrame: "L",
  analyzeWeedFrame: "W",
  pauseWeedScan: "P",
  returnLiveCamera: "R",
  exportWeedCoordinates: "E",
  exportLibrary: "E",
  libraryCaptured: "Y",
  libraryRegional: "V",
  libraryMap: "M",
  applyCrop: "C",
  identifyCrop: "I",
  diagnostics: "D",
  phoneCapture: "Space",
  tryAnotherView: "R",
});

export const SHORTCUT_HELP = Object.freeze([
  { key: "1", label: "Scan for Plants" },
  { key: "2", label: "Open Library" },
  { key: "3", label: "Weed Detection" },
  { key: "A", label: "Ask Botanika" },
  { key: "H", label: "Go Home" },
  { key: "Esc", label: "Cancel / Home / close panel" },
  { key: "F1", label: "Show these shortcuts" },
  { key: "D", label: "Capability diagnostics" },
  { key: "Space", label: "Manual capture / phone capture", scope: "Scan" },
  { key: "L", label: "Choose a local image/frame", scope: "Scan / Weeds" },
  { key: "C", label: "Capture from image / apply crop", scope: "Scan / paired phone" },
  { key: "X", label: "Clear selected image", scope: "Local-image scan" },
  { key: "S", label: "Save to Library", scope: "Accepted result" },
  { key: "R", label: "Retake / try another view", scope: "Scan" },
  { key: "G", label: "Another angle", scope: "Scan" },
  { key: "W", label: "Analyze weed frame", scope: "Weeds" },
  { key: "P", label: "Pause / resume live weed scan", scope: "Weeds" },
  { key: "E", label: "Export library / weed coordinates", scope: "Library / Weeds" },
  { key: "Y", label: "Show your captured plants", scope: "Library" },
  { key: "V", label: "Show the Vellore regional checklist", scope: "Library" },
  { key: "M", label: "Show the observation map", scope: "Library" },
  { key: "I", label: "Identify crop", scope: "Paired phone" },
]);

const EDITABLE_TAGS = new Set(["INPUT", "TEXTAREA", "SELECT"]);

export function isEditableTarget(target) {
  if (!target) return false;
  const tagName = String(target.tagName || "").toUpperCase();
  if (EDITABLE_TAGS.has(tagName)) return true;
  if (target.isContentEditable === true) return true;

  // `closest` covers contenteditable wrappers in the browser. The parent walk
  // keeps the helper useful with small test doubles and embedded browsers.
  if (typeof target.closest === "function") {
    try {
      if (target.closest("[contenteditable=\"true\"]")) return true;
    } catch {
      // Ignore malformed test doubles; the parent walk below still applies.
    }
  }
  let current = target.parentElement;
  while (current) {
    if (current.isContentEditable === true) return true;
    if (String(current.getAttribute?.("contenteditable") || "").toLowerCase() === "true") return true;
    current = current.parentElement;
  }
  return false;
}

export function isDialogTarget(target) {
  if (!target) return false;
  if (typeof target.closest === "function") {
    try {
      if (target.closest("dialog[open], [role=\"dialog\"], [data-hotkeys-block=\"true\"]")) return true;
    } catch {
      // Fall through to the lightweight parent walk.
    }
  }
  let current = target;
  while (current) {
    const tagName = String(current.tagName || "").toUpperCase();
    const role = String(current.getAttribute?.("role") || "").toLowerCase();
    const blocked = String(current.getAttribute?.("data-hotkeys-block") || "").toLowerCase();
    if (tagName === "DIALOG" || role === "dialog" || blocked === "true") return true;
    current = current.parentElement;
  }
  return false;
}

export function isShortcutBlocked(event, options = {}) {
  if (!event || event.defaultPrevented) return true;
  if (event.ctrlKey || event.altKey || event.metaKey) return true;
  if (isEditableTarget(event.target)) return true;
  if (options.overlaysOpen || isDialogTarget(event.target)) return true;

  // A click/keydown can land on the page root while a contained dialog or
  // popover is open. In that case target.closest() has no overlay ancestor,
  // so also inspect the owner document when one is available.
  const ownerDocument = options.documentLike
    || event.target?.ownerDocument
    || (typeof document !== "undefined" ? document : null);
  try {
    return Boolean(ownerDocument?.querySelector?.("dialog[open], [role=\"dialog\"], [data-hotkeys-block=\"true\"]"));
  } catch {
    return false;
  }
}

/**
 * Convert browser key values and data-hotkey values to one comparable form.
 * Space is special because KeyboardEvent.key is a literal space while
 * KeyboardEvent.code is `Space`.
 */
export function normalizeShortcutKey(value) {
  const raw = typeof value === "object" && value !== null
    ? (value.code === "Space" ? "Space" : value.key || value.code)
    : value;
  const normalized = String(raw || "").trim().toLowerCase();
  if (normalized === "" || normalized === "spacebar" || normalized === "space") return "space";
  if (normalized === "esc") return "escape";
  if (/^key[a-z]$/.test(normalized)) return normalized.slice(3);
  if (/^digit[0-9]$/.test(normalized)) return normalized.slice(5);
  return normalized;
}

/**
 * Find an enabled shortcut control in the current page.  `root` is injectable
 * for tests and also lets embedded kiosk shells provide their owner document.
 */
export function findShortcutTarget(eventOrKey, root = null) {
  const normalized = normalizeShortcutKey(eventOrKey);
  if (!normalized) return null;
  const ownerDocument = root
    || (typeof eventOrKey === "object" && eventOrKey?.target?.ownerDocument)
    || (typeof document !== "undefined" ? document : null);
  const controls = ownerDocument?.querySelectorAll?.("[data-hotkey]") || [];
  for (const control of controls) {
    const advertised = control?.dataset?.hotkey
      || control?.getAttribute?.("data-hotkey")
      || "";
    if (normalizeShortcutKey(advertised) !== normalized) continue;
    if (control.disabled || control.getAttribute?.("aria-disabled") === "true") continue;
    if (isDialogTarget(control)) continue;
    return control;
  }
  return null;
}

export function shortcutAction(key) {
  const normalized = normalizeShortcutKey(key);
  return APP_SHORTCUTS[normalized] || null;
}

export function shortcutLabel(action) {
  return Object.entries(APP_SHORTCUTS)
    .find(([, value]) => value === action)?.[0] || "";
}
