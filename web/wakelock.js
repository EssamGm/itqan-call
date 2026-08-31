/*
 * Keep the screen awake for as long as a call is running.
 *
 * A phone that locks its screen suspends the page, and microphone capture
 * stops with it. Nothing about this is visible to either person: the server
 * keeps recording and simply receives nothing. On one real call a trainee's
 * audio vanished for 97 seconds exactly this way, and the two of them spent
 * another minute guessing at the mic button before giving up on it.
 *
 * The browser releases the lock on its own whenever the page is hidden, so it
 * has to be taken again on the way back rather than acquired once and trusted.
 */

let lock = null;
let wanted = false;

async function acquire() {
  if (!wanted || lock || !("wakeLock" in navigator)) return;
  try {
    lock = await navigator.wakeLock.request("screen");
    // The browser drops it for its own reasons too, not only on hide.
    lock.addEventListener("release", () => { lock = null; });
  } catch (err) {
    // Refused, unsupported, or the page was not visible at the time. Left
    // silent deliberately: the call still works without it, and a warning
    // during connection would be one more thing to read at the worst moment.
    lock = null;
  }
}

function onVisibilityChange() {
  if (document.visibilityState === "visible") acquire();
}

/** Ask the device to stay awake. Safe to call when unsupported. */
export function keepAwake() {
  wanted = true;
  document.addEventListener("visibilitychange", onVisibilityChange);
  acquire();
}

/** Release it, and stop trying to reacquire. */
export function letSleep() {
  wanted = false;
  document.removeEventListener("visibilitychange", onVisibilityChange);
  if (lock) {
    lock.release().catch(() => {});
    lock = null;
  }
}

/** Whether this browser offers the lock at all - Safari on iOS did not until 16.4. */
export function wakeLockSupported() {
  return "wakeLock" in navigator;
}
