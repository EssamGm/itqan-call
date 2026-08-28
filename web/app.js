/*
 * Itqan call app — trainee side. Voice only.
 *
 * Knows nothing about the transport vendor; it drives whichever CallProvider
 * it is handed. Swapping Daily for Zoom means changing the import below.
 */

import { DailyProvider, ROLE_TRAINEE } from "./provider-daily.js";

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
    // The name now travels with the session: it is shown in this trainee's
    // bubble in the published video, so it is no longer kept device-local.
    await provider.createSession(ROLE_TRAINEE, traineeName());
    await provider.join({
      onRemoteAudio: (stream) => {
        const el = $("remote-audio");
        el.srcObject = stream;
        el.play().catch(() => {});
      },
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

/* --------------------------------------------------------- call: controls */

let micOn = true;

$("btn-mic").addEventListener("click", () => {
  micOn = !micOn;
  provider.setMic(micOn);
  $("btn-mic").classList.toggle("off", !micOn);
});

/**
 * Speaker toggle: mutes the incoming audio on this device only.
 *
 * The other side keeps talking and the recording is unaffected - each person's
 * audio is captured from their own uplink, so muting your speaker never
 * touches what gets published.
 */
let speakerOn = true;

$("btn-speaker").addEventListener("click", () => {
  speakerOn = !speakerOn;
  const el = $("remote-audio");
  el.muted = !speakerOn;
  if (speakerOn) el.play().catch(() => {});
  $("btn-speaker").classList.toggle("off", !speakerOn);
});

$("btn-hangup").addEventListener("click", () => endCall());

async function endCall() {
  const seconds = stopTimer();
  await provider.leave().catch(() => {});
  const audio = $("remote-audio");
  audio.srcObject = null;
  audio.muted = false;   // do not carry a muted speaker into the next call
  micOn = true;
  speakerOn = true;
  $("btn-mic").classList.remove("off");
  $("btn-speaker").classList.remove("off");
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
