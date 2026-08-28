/*
 * Itqan call app — screen flow and controls.
 *
 * Knows nothing about the transport vendor; it drives whichever CallProvider
 * it is handed. Swapping Daily for Zoom means changing the import below.
 */

import { DailyProvider } from "./provider-daily.js";

const provider = new DailyProvider();

const $ = (id) => document.getElementById(id);
const NAME_KEY = "itqan.trainee.name";

let timerHandle = null;
let startedAt = 0;

/* ---------------------------------------------------------------- screens */

function show(id) {
  for (const s of document.querySelectorAll(".screen")) {
    s.classList.toggle("active", s.id === id);
  }
}

function traineeName() {
  return (localStorage.getItem(NAME_KEY) || "").trim();
}

/* ------------------------------------------------------------------ timer */

function fmt(totalSeconds) {
  const m = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const s = String(totalSeconds % 60).padStart(2, "0");
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
  return Math.floor((Date.now() - startedAt) / 1000);
}

/* ------------------------------------------------------------- name entry */

const nameInput = $("name-input");
const nameSave = $("name-save");

nameInput.addEventListener("input", () => {
  nameSave.disabled = nameInput.value.trim().length < 2;
});
nameInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !nameSave.disabled) nameSave.click();
});

nameSave.addEventListener("click", () => {
  localStorage.setItem(NAME_KEY, nameInput.value.trim());
  goIdle();
});

function goIdle() {
  $("who").textContent = traineeName();
  $("idle-status").innerHTML = "&nbsp;";
  show("screen-idle");
}

/* ------------------------------------------------------- call: consent gate */

$("call-btn").addEventListener("click", () => {
  $("consent-status").innerHTML = "&nbsp;";
  show("screen-consent");
});

$("consent-ok").addEventListener("click", async () => {
  const btn = $("consent-ok");
  const status = $("consent-status");
  btn.disabled = true;
  status.classList.remove("error");
  status.textContent = "جارٍ الاتصال…";

  try {
    // The name stays on this device; the server is told a role, nothing more.
    await provider.createSession("trainee");
    await provider.join({
      onLocalTrack: (stream) => attach($("local"), stream, true),
      onRemoteTrack: (stream) => attach($("remote"), stream, false),
      onJoined: () => {
        show("screen-call");
        startTimer();
      },
      onPeerLeft: () => endCall(),
      onError: (msg) => fail(msg),
    });
  } catch (err) {
    fail(err && err.message ? err.message : "تعذّر بدء المكالمة");
  } finally {
    btn.disabled = false;
  }

  function fail(msg) {
    status.classList.add("error");
    status.textContent = msg;
  }
});

function attach(el, stream, muted) {
  el.srcObject = stream;
  el.muted = !!muted;
  // Autoplay can still be refused; ignore rather than break the call.
  el.play().catch(() => {});
}

/* --------------------------------------------------------- call: controls */

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
  const seconds = stopTimer();
  await provider.leave().catch(() => {});
  for (const id of ["local", "remote"]) {
    const el = $(id);
    el.srcObject = null;
  }
  micOn = camOn = true;
  $("btn-mic").classList.remove("off");
  $("btn-cam").classList.remove("off");
  $("ended-duration").textContent = seconds > 0 ? `المدة ${fmt(seconds)}` : "";
  show("screen-ended");
}

$("back-btn").addEventListener("click", goIdle);

/* ------------------------------------------------------------------ boot */

if (traineeName()) {
  goIdle();
} else {
  show("screen-name");
  nameInput.focus();
}
