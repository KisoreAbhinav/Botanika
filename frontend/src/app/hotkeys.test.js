import test from "node:test";
import assert from "node:assert/strict";

import {
  isDialogTarget,
  isEditableTarget,
  isShortcutBlocked,
  shortcutAction,
} from "./hotkeys.js";

test("app shortcuts map to the kiosk destinations", () => {
  assert.equal(shortcutAction("1"), "scan");
  assert.equal(shortcutAction("2"), "library");
  assert.equal(shortcutAction("3"), "weeds");
  assert.equal(shortcutAction("A"), "ask");
  assert.equal(shortcutAction("H"), "home");
  assert.equal(shortcutAction("Escape"), "home");
  assert.equal(shortcutAction("x"), null);
});

test("typing targets and contenteditable regions are protected", () => {
  assert.equal(isEditableTarget({ tagName: "input" }), true);
  assert.equal(isEditableTarget({ tagName: "TEXTAREA" }), true);
  assert.equal(isEditableTarget({ tagName: "select" }), true);
  assert.equal(isEditableTarget({ tagName: "button" }), false);
  assert.equal(isEditableTarget({ tagName: "div", isContentEditable: true }), true);
});

test("dialog targets block navigation, including lightweight test doubles", () => {
  const dialog = { tagName: "DIALOG", parentElement: null };
  const child = { tagName: "button", parentElement: dialog };
  assert.equal(isDialogTarget(child), true);
  assert.equal(isShortcutBlocked({ key: "1", target: child }), true);
  assert.equal(isShortcutBlocked({ key: "1", target: { tagName: "button" } }), false);
});

test("an open overlay blocks page-root events even when the target is outside it", () => {
  const pageRoot = { tagName: "main" };
  assert.equal(
    isShortcutBlocked({ key: "1", target: pageRoot }, { overlaysOpen: true }),
    true,
  );
  assert.equal(
    isShortcutBlocked(
      { key: "1", target: pageRoot },
      { documentLike: { querySelector: () => ({}) } },
    ),
    true,
  );
  assert.equal(
    isShortcutBlocked(
      { key: "1", target: pageRoot },
      { documentLike: { querySelector: () => null } },
    ),
    false,
  );
});

test("modified and already-handled events are never consumed", () => {
  const target = { tagName: "button" };
  assert.equal(isShortcutBlocked({ key: "1", target, ctrlKey: true }), true);
  assert.equal(isShortcutBlocked({ key: "1", target, altKey: true }), true);
  assert.equal(isShortcutBlocked({ key: "1", target, metaKey: true }), true);
  assert.equal(isShortcutBlocked({ key: "1", target, defaultPrevented: true }), true);
  assert.equal(isShortcutBlocked({ key: "1", target: { tagName: "input" } }), true);
});
