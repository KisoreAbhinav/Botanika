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
});

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

export function shortcutAction(key) {
  const normalized = String(key || "").toLowerCase();
  return APP_SHORTCUTS[normalized] || null;
}

export function shortcutLabel(action) {
  return Object.entries(APP_SHORTCUTS)
    .find(([, value]) => value === action)?.[0] || "";
}
