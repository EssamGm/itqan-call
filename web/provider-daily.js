/*
 * Vendor adapter — Daily.co. Voice only.
 *
 * Everything that knows the transport vendor's name lives in this file and in
 * the matching server endpoints. The UI and the post-call renderer talk only to
 * the CallProvider shape below, so swapping to Zoom Video SDK or LiveKit means
 * writing a sibling of this file, not touching the app.
 *
 * No camera is ever requested. This is a coaching call: the published video
 * shows named bubbles, not faces, so there is no reason to capture video, and
 * not capturing it removes a whole class of privacy and bandwidth concern.
 */

import { API_BASE } from "./config.js";

export const ROLE_COACH = "coach";
export const ROLE_TRAINEE = "trainee";

// Fixed per role so the laptop agent can tell the two recordings apart when it
// pairs them. instanceId only has to be unique within a room, and each call
// gets a fresh room, so constants are safe.
const INSTANCE_IDS = {
  [ROLE_COACH]: "5c0ac400-0000-4000-8000-000000000001",
  [ROLE_TRAINEE]: "5c0ac400-0000-4000-8000-000000000002",
};

// A call must not be able to outlive the conversation.
//
// When one side's connection dropped, the other sat in an empty room with the
// timer still running, unaware, until they hung up by hand - and Daily bills
// for every minute of it. Nothing on the server can see that: the room is
// still occupied, so it looks like a call in progress.
const ALONE_AFTER_ANSWER_MS = 45000;   // peer vanished mid-call
const ALONE_WAITING_MS = 150000;       // nobody ever answered
const CONNECTION_LOST_MS = 25000;      // our own connection never came back
const WATCHDOG_TICK_MS = 2000;

// Audio is the entire product here, so these matter more than usual.
const AUDIO_CONSTRAINTS = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
};

export class DailyProvider {
  constructor({ apiBase = API_BASE } = {}) {
    this.apiBase = apiBase;
    this.call = null;
    this.session = null;
  }

  async _post(path, body) {
    const res = await fetch(`${this.apiBase}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(`request failed (${res.status})`);
    return res.json();
  }

  /** Create a room and mint a token. The API key never reaches the browser. */
  async createSession(role = ROLE_TRAINEE, name = "") {
    this.session = await this._post("/session", { role, name });
    return this.session;
  }

  /** Is someone waiting? Returns the pending call (with their name), or null. */
  async pendingCall() {
    const res = await fetch(`${this.apiBase}/pending`);
    if (!res.ok) throw new Error(`could not check for calls (${res.status})`);
    return (await res.json()).pending || null;
  }

  /** Join a room a trainee already opened, as the coach. */
  async answer(sessionId, name = "") {
    this.session = await this._post("/answer", { sessionId, name });
    return this.session;
  }

  async join(handlers = {}) {
    if (!this.session) throw new Error("createSession must run before join");
    const { onRemoteAudio, onJoined, onPeerLeft, onError, onAutoEnd } = handlers;

    this.call = window.DailyIframe.createCallObject({
      subscribeToTracksAutomatically: true,
    });

    const emitAudio = (ev) => {
      const p = ev && ev.participant;
      if (!p || p.local) return;
      const t = p.tracks && p.tracks.audio;
      if (!t || t.state !== "playable" || !t.persistentTrack) return;
      const stream = new MediaStream([t.persistentTrack]);
      onRemoteAudio && onRemoteAudio(stream, p.user_name || "");
    };

    this.call
      .on("track-started", emitAudio)
      .on("participant-updated", emitAudio)
      .on("participant-joined", emitAudio)
      .on("joined-meeting", () => onJoined && onJoined())
      .on("participant-left", () => onPeerLeft && onPeerLeft())
      .on("error", (e) =>
        onError && onError(e && e.errorMsg ? e.errorMsg : "call error"));

    await this.call.join({
      url: this.session.roomUrl,
      token: this.session.token,
      audioSource: true,
      videoSource: false,          // never open the camera
      startVideoOff: true,
      userMediaAudioConstraints: AUDIO_CONSTRAINTS,
    });

    // Only after a successful join: a call that has begun is a call that can
    // be left running by accident.
    this._startWatchdog({ onEnded: (reason) => onAutoEnd && onAutoEnd(reason) });

    return this.session;
  }

  /**
   * Watch for a call that has stopped being a call.
   *
   * Three ways that happens: the other side disappears mid-conversation, they
   * never answer at all, or our own connection drops and does not return. All
   * three end the call rather than leaving it running.
   *
   * The mid-call timer only starts once both people have actually been present,
   * so a trainee waiting to be answered is never cut off by it.
   */
  _startWatchdog({ onEnded } = {}) {
    let everBothPresent = false;
    let aloneSince = null;
    let interruptedSince = null;

    const onNetwork = (ev) => {
      const state = ev && (ev.event || ev.type);
      if (state === "interrupted") {
        if (!interruptedSince) interruptedSince = Date.now();
      } else if (state === "connected") {
        interruptedSince = null;
      }
    };
    this.call.on("network-connection", onNetwork);

    const finish = (reason) => {
      this._stopWatchdog();
      onEnded && onEnded(reason);
    };

    this._watchdogOff = () => this.call && this.call.off("network-connection", onNetwork);
    this._watchdog = setInterval(() => {
      if (!this.call) return this._stopWatchdog();

      const people = Object.values(this.call.participants() || {})
        .filter((p) => p && p.session_id);
      if (people.length >= 2) {
        everBothPresent = true;
        aloneSince = null;
      } else if (!aloneSince) {
        aloneSince = Date.now();
      }

      const limit = everBothPresent ? ALONE_AFTER_ANSWER_MS : ALONE_WAITING_MS;
      if (aloneSince && Date.now() - aloneSince > limit) {
        return finish(everBothPresent ? "peer-gone" : "no-answer");
      }
      if (interruptedSince && Date.now() - interruptedSince > CONNECTION_LOST_MS) {
        return finish("connection-lost");
      }
    }, WATCHDOG_TICK_MS);
  }

  _stopWatchdog() {
    if (this._watchdog) clearInterval(this._watchdog);
    this._watchdog = null;
    if (this._watchdogOff) this._watchdogOff();
    this._watchdogOff = null;
  }

  /** Wait until both people are in the room. Returns the participant list. */
  async waitForPeer(timeoutMs = 15000) {
    const deadline = Date.now() + timeoutMs;
    let people = [];
    while (Date.now() < deadline) {
      people = Object.values(this.call.participants() || {})
        .filter((p) => p && p.session_id);
      if (people.length >= 2) return people;
      await new Promise((r) => setTimeout(r, 500));
    }
    return people;
  }

  /**
   * Start one audio recording per participant.
   *
   * Two concurrent instances rather than one mixed file, so the renderer knows
   * who is speaking. Recording must be started from a client: Daily's
   * start_cloud_recording token property covers only plain "cloud" mode, and
   * the coach's token is the room owner.
   *
   * Resolves true only when Daily confirms both. Nothing is shown during the
   * call on success; only failure surfaces, so a session is never lost
   * silently while the call still feels like an ordinary phone call.
   */
  async startRecording({ timeoutMs = 20000 } = {}) {
    if (!this.call) return false;

    const people = await this.waitForPeer(timeoutMs);
    if (people.length < 2) {
      this.lastRecordingError = "peer-absent";
      return false;
    }

    // startRecording resolves even when Daily refuses the request - the
    // refusal arrives as a recording-error event. Trusting the promise made
    // the app report success while nothing was being recorded, so wait for
    // Daily to actually confirm each one.
    const confirmed = new Set();
    const failures = [];
    const onStarted = (e) => e && e.instanceId && confirmed.add(e.instanceId);
    const onError = (e) => failures.push((e && e.errorMsg) || "recording error");
    this.call.on("recording-started", onStarted);
    this.call.on("recording-error", onError);

    try {
      for (const p of people) {
        const role = p.user_id === ROLE_COACH ? ROLE_COACH : ROLE_TRAINEE;
        try {
          await this.call.startRecording({
            type: "cloud-audio-only",
            instanceId: INSTANCE_IDS[role],
            layout: {
              preset: "audio-only",
              participants: { audio: [p.session_id] },
            },
          });
        } catch (_) {
          /* try the other participant regardless */
        }
      }

      const until = Date.now() + 12000;
      while (Date.now() < until && confirmed.size < 2 && !failures.length) {
        await new Promise((r) => setTimeout(r, 300));
      }
    } finally {
      this.call.off("recording-started", onStarted);
      this.call.off("recording-error", onError);
    }

    if (failures.length) this.lastRecordingError = failures[0];
    return confirmed.size === 2;
  }

  /**
   * Leave the call.
   *
   * endForEveryone deletes the room server-side. Leaving on the client only
   * disconnects this browser - the other side stays connected and Daily keeps
   * billing for a call nobody is having. Only the coach does this; a trainee
   * hanging up should not be able to end the coach's session.
   */
  async leave({ endForEveryone = false } = {}) {
    this._stopWatchdog();
    const sessionId = this.session && this.session.sessionId;
    try {
      if (this.call) await this.call.leave();
    } finally {
      if (this.call) {
        this.call.destroy();
        this.call = null;
      }
    }
    if (endForEveryone && sessionId) {
      try {
        await fetch(`${this.apiBase}/end`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sessionId }),
        });
      } catch (_) {
        /* the room also expires on its own; nothing useful to do here */
      }
    }
  }

  /** Any call still running, so one can never be live without the coach knowing. */
  async activeCalls() {
    const res = await fetch(`${this.apiBase}/end`);
    if (!res.ok) return [];
    return (await res.json()).active || [];
  }

  setMic(on) {
    if (this.call) this.call.setLocalAudio(!!on);
  }

  /*
   * On earpiece versus speakerphone, which a real phone call offers:
   *
   * A web page cannot do it on Android. Choosing an audio output means
   * setSinkId(), which Chrome on Android does not implement - it is desktop
   * only, Firefox has it behind a flag, and Safari leaves the choice to the
   * OS entirely. Routing to the earpiece is a privilege the browser keeps for
   * itself, so there is nothing to call.
   *
   * Wired and Bluetooth headsets route normally, because the OS handles that
   * below the browser. Anything more would need a native app, which this
   * project deliberately is not.
   *
   * Left here so it is not attempted again.
   */
}
