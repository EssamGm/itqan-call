/*
 * Coach app — Essam's side. Voice only.
 *
 * Polls for a waiting trainee and answers into their room. The in-call screen
 * is deliberately identical to the trainee's: an ordinary voice call, with no
 * hint that anything is being recorded.
 */

import { DailyProvider } from "./provider-daily.js";
import { COACH_NAME } from "./config.js";

const provider = new DailyProvider();
const $ = (id) => document.getElementById(id);

const POLL_MS = 4000;

let pollHandle = null;
let pending = null;
let timerHandle = null;
let startedAt = 0;
let inCall = false;

function show(id) {
  for (const s of document.querySelectorAll(".screen")) {
    s.classList.toggle("active", s.id === id);
  }
}

/* ------------------------------------------------------------------ timer */

function fmt(total) {
  const m = String(Math.floor(total / 60)).padStart(2, "0");
  const s = String(total % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function startTimer() {
  startedAt = Date.now();
  const tick = () => {
    $("timer").textContent = fmt(Math.floor((Date.now() - startedAt) / 1000));
  };
  tick();
  timerHandle = setInterval(tick, 1000);
}

function stopTimer() {
  if (timerHandle) clearInterval(timerHandle);
  timerHandle = null;
  return startedAt ? Math.floor((Date.now() - startedAt) / 1000) : 0;
}

/* ------------------------------------------------------- polling for calls */

async function poll() {
  if (inCall) return;
  try {
    setPending(await provider.pendingCall());
    $("idle-status").classList.remove("error");
    $("idle-status").innerHTML = "&nbsp;";
  } catch (err) {
    // A failed poll is not worth alarming about; the next one usually works.
    $("idle-status").classList.add("error");
    $("idle-status").textContent = "تعذّر الاتصال بالخادم";
  }
}

function setPending(found) {
  pending = found;
  const waiting = !!found;
  $("dot").classList.toggle("live", waiting);
  // Show who is calling, the way a phone shows a contact name.
  $("idle-text").textContent = waiting
    ? (found.name ? `${found.name} ينتظر` : "متدرب ينتظر")
    : "لا توجد مكالمات";
  $("answer-btn").style.display = waiting ? "grid" : "none";
  $("answer-btn").classList.toggle("ringing", waiting);
}

/* ----------------------------------------------------------------- answer */

$("answer-btn").addEventListener("click", async () => {
  if (!pending) return;
  const btn = $("answer-btn");
  btn.disabled = true;
  inCall = true;
  $("peer-title").textContent = pending.name || "المتدرب";

  try {
    await provider.answer(pending.sessionId, COACH_NAME);
    await provider.join({
      onRemoteAudio: (stream) => {
        const el = $("remote-audio");
        el.srcObject = stream;
        el.play().catch(() => {});
      },
      onJoined: async () => {
        show("screen-call");
        startTimer();
        // Raw per-person recording cannot be auto-started by the token, so
        // start it here. Silent on success; loud only if it fails.
        if (!(await provider.startRecording())) warnNotRecording();
      },
      onPeerLeft: () => endCall(),
      onError: () => endCall(),
    });
  } catch (err) {
    inCall = false;
    $("idle-status").classList.add("error");
    $("idle-status").textContent = err.message || "تعذّر الرد";
  } finally {
    btn.disabled = false;
  }
});

/** Only ever shown on the coach's screen, and only when recording failed. */
function warnNotRecording() {
  const stage = document.querySelector("#screen-call .voice-stage");
  if (!stage || stage.querySelector(".rec-warning")) return;
  const el = document.createElement("div");
  el.className = "rec-warning";
  el.textContent = "لا يتم التسجيل";
  stage.appendChild(el);
}

/* --------------------------------------------------------------- controls */

let micOn = true;

$("btn-mic").addEventListener("click", () => {
  micOn = !micOn;
  provider.setMic(micOn);
  $("btn-mic").classList.toggle("off", !micOn);
});

$("btn-hangup").addEventListener("click", () => endCall());

async function endCall() {
  if (!inCall) return;
  const seconds = stopTimer();
  await provider.leave().catch(() => {});
  $("remote-audio").srcObject = null;
  micOn = true;
  $("btn-mic").classList.remove("off");
  const warn = document.querySelector(".rec-warning");
  if (warn) warn.remove();
  inCall = false;
  setPending(null);
  $("ended-duration").textContent = seconds > 0 ? `المدة ${fmt(seconds)}` : "";
  show("screen-ended");
}

$("back-btn").addEventListener("click", () => {
  show("screen-idle");
  poll();
});

/* -------------------------------------------------- push notifications */

/**
 * Subscribe this device to incoming-call notifications.
 *
 * Must run from a tap: browsers refuse a permission prompt that was not asked
 * for. Kept entirely optional - polling still works without it, so declining
 * notifications degrades the experience rather than breaking it.
 */
function b64ToBytes(base64) {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4))
    .replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

async function enablePush() {
  const btn = $("enable-push");
  const status = $("idle-status");
  btn.disabled = true;
  try {
    const reg = await navigator.serviceWorker.ready;
    const { publicKey } = await (await fetch(`/api/subscribe`)).json();
    if (!publicKey) throw new Error("لم يتم إعداد التنبيهات على الخادم");

    if ((await Notification.requestPermission()) !== "granted") {
      throw new Error("لم يُسمح بالتنبيهات");
    }

    const sub =
      (await reg.pushManager.getSubscription()) ||
      (await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: b64ToBytes(publicKey),
      }));

    const res = await fetch(`/api/subscribe`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subscription: sub.toJSON() }),
    });
    if (!res.ok) throw new Error("تعذّر حفظ الاشتراك على الخادم");

    btn.style.display = "none";
    status.classList.remove("error");
    status.textContent = "التنبيهات مفعّلة";
  } catch (err) {
    status.classList.add("error");
    status.textContent = err.message || "تعذّر تفعيل التنبيهات";
  } finally {
    btn.disabled = false;
  }
}

async function initPush() {
  const btn = $("enable-push");
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
  btn.addEventListener("click", enablePush);

  // Offer the button unless this device is already subscribed.
  try {
    const reg = await navigator.serviceWorker.ready;
    const existing = await reg.pushManager.getSubscription();
    if (!existing || Notification.permission !== "granted") {
      btn.style.display = "inline-block";
    }
  } catch (_) {
    btn.style.display = "inline-block";
  }
}

/* ------------------------------------------------------------------ boot */

poll();
pollHandle = setInterval(poll, POLL_MS);
initPush();
