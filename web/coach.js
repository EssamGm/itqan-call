/*
 * Coach app — Essam's side.
 *
 * Polls for a waiting trainee and answers into their room. The in-call screen
 * is deliberately identical to the trainee's: plain, ordinary, no hint that
 * anything is being recorded.
 */

import { DailyProvider } from "./provider-daily.js";

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
    const found = await provider.pendingCall();
    setPending(found);
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
  $("idle-text").textContent = waiting ? "متدرب ينتظر" : "لا توجد مكالمات";
  $("answer-btn").style.display = waiting ? "grid" : "none";
  $("answer-btn").classList.toggle("ringing", waiting);
}

function startPolling() {
  poll();
  if (!pollHandle) pollHandle = setInterval(poll, POLL_MS);
}

/* ----------------------------------------------------------------- answer */

$("answer-btn").addEventListener("click", async () => {
  if (!pending) return;
  const btn = $("answer-btn");
  btn.disabled = true;
  inCall = true;

  try {
    await provider.answer(pending.sessionId);
    await provider.join({
      onLocalTrack: (stream) => attach($("local"), stream, true),
      onRemoteTrack: (stream) => attach($("remote"), stream, false),
      onJoined: async () => {
        show("screen-call");
        startTimer();
        // Raw-tracks cannot be auto-started by the token, so start it here.
        // Silent on success; loud only if it fails, so a session is never
        // lost without Essam knowing, while the call still feels ordinary.
        const ok = await provider.startRecording();
        if (!ok) warnNotRecording();
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
  const stage = document.querySelector("#screen-call .stage");
  if (!stage || stage.querySelector(".rec-warning")) return;
  const el = document.createElement("div");
  el.className = "rec-warning";
  el.textContent = "لا يتم التسجيل";
  stage.appendChild(el);
}

function attach(el, stream, muted) {
  el.srcObject = stream;
  el.muted = !!muted;
  el.play().catch(() => {});
}

/* --------------------------------------------------------------- controls */

let micOn = true;
let camOn = true;

$("btn-mic").addEventListener("click", () => {
  micOn = !micOn;
  provider.setMic(micOn);
  $("btn-mic").classList.toggle("off", !micOn);
});

$("btn-cam").addEventListener("click", () => {
  camOn = !camOn;
  provider.setCam(camOn);
  $("btn-cam").classList.toggle("off", !camOn);
});

$("btn-hangup").addEventListener("click", () => endCall());

async function endCall() {
  if (!inCall) return;
  const seconds = stopTimer();
  await provider.leave().catch(() => {});
  for (const id of ["local", "remote"]) $(id).srcObject = null;
  micOn = camOn = true;
  $("btn-mic").classList.remove("off");
  $("btn-cam").classList.remove("off");
  inCall = false;
  setPending(null);
  $("ended-duration").textContent = seconds > 0 ? `المدة ${fmt(seconds)}` : "";
  show("screen-ended");
}

$("back-btn").addEventListener("click", () => {
  show("screen-idle");
  poll();
});

/* ------------------------------------------------------------------ boot */

startPolling();
