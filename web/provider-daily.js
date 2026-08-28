/*
 * Vendor adapter — Daily.co.
 *
 * Everything that knows the transport vendor's name lives in this file and in
 * the matching server endpoint. The UI (app.js) and the post-call renderer talk
 * only to the CallProvider shape below, so swapping to Zoom Video SDK or
 * LiveKit means writing a sibling of this file, not touching the app.
 *
 * The contract:
 *   createSession(traineeName) -> { sessionId, roomUrl, token }
 *   join(handlers)             -> connects, wires media, starts recording
 *   leave()                    -> disconnects and stops recording
 *   setMic(on) / setCam(on)    -> local track toggles
 *
 * handlers: { onLocalTrack, onRemoteTrack, onJoined, onPeerLeft, onError }
 */

import { API_BASE } from "./config.js";

export const ROLE_COACH = "coach";
export const ROLE_TRAINEE = "trainee";

// Fixed per role so the laptop agent can tell the two recordings apart when it
// pairs them later. instanceId only has to be unique within a room, and each
// call gets a fresh room, so constants are safe.
const INSTANCE_IDS = {
  [ROLE_COACH]: "5c0ac400-0000-4000-8000-000000000001",
  [ROLE_TRAINEE]: "5c0ac400-0000-4000-8000-000000000002",
};

// Audio is the priority for this project: a choppy voice ruins a coaching
// call, whereas soft video is tolerable. These constraints keep the mic clean,
// and the send settings below let Daily sacrifice video first when the network
// degrades rather than starving the audio stream.
const AUDIO_CONSTRAINTS = {
  echoCancellation: true,
  noiseSuppression: true,
  autoGainControl: true,
};

const VIDEO_CONSTRAINTS = {
  width: { ideal: 1280 },
  height: { ideal: 720 },
  frameRate: { ideal: 30, max: 30 },
};

export class DailyProvider {
  constructor({ apiBase = API_BASE } = {}) {
    this.apiBase = apiBase;
    this.call = null;
    this.session = null;
  }

  /**
   * Ask our own server to mint a room + token. The API key never reaches the
   * browser, and no trainee name is sent: participants are labelled by role
   * only, so no personal data reaches the host or the transport vendor.
   */
  async createSession(role = "trainee") {
    const res = await fetch(`${this.apiBase}/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role }),
    });
    if (!res.ok) {
      throw new Error(`could not start a session (${res.status})`);
    }
    this.session = await res.json();
    return this.session;
  }

  /** Is a trainee waiting? Returns the pending call, or null. */
  async pendingCall() {
    const res = await fetch(`${this.apiBase}/pending`);
    if (!res.ok) throw new Error(`could not check for calls (${res.status})`);
    const data = await res.json();
    return data.pending || null;
  }

  /** Join a room a trainee already opened, as the coach. */
  async answer(sessionId) {
    const res = await fetch(`${this.apiBase}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sessionId }),
    });
    if (!res.ok) throw new Error(`could not answer (${res.status})`);
    this.session = await res.json();
    return this.session;
  }

  async join(handlers = {}) {
    if (!this.session) throw new Error("createSession must run before join");
    const { onLocalTrack, onRemoteTrack, onJoined, onPeerLeft, onError } = handlers;

    this.call = window.DailyIframe.createCallObject({
      subscribeToTracksAutomatically: true,
      dailyConfig: {
        // Prefer keeping audio intact over keeping video sharp.
        useDevicePreferenceCookies: true,
      },
    });

    const emitTracks = (ev) => {
      if (!ev || !ev.participant) return;
      const p = ev.participant;
      const stream = new MediaStream();
      for (const key of ["video", "audio"]) {
        const t = p.tracks[key];
        if (t && t.state === "playable" && t.persistentTrack) {
          stream.addTrack(t.persistentTrack);
        }
      }
      if (!stream.getTracks().length) return;
      if (p.local) onLocalTrack && onLocalTrack(stream);
      else onRemoteTrack && onRemoteTrack(stream, p.user_name || "");
    };

    this.call
      .on("track-started", emitTracks)
      .on("participant-updated", emitTracks)
      .on("joined-meeting", (ev) => {
        emitTracks({ participant: ev.participants.local });
        onJoined && onJoined();
      })
      .on("participant-joined", emitTracks)
      .on("participant-left", () => onPeerLeft && onPeerLeft())
      .on("error", (e) => onError && onError(e && e.errorMsg ? e.errorMsg : "call error"));

    await this.call.join({
      url: this.session.roomUrl,
      token: this.session.token,
      userName: this.session.userName,
      audioSource: true,
      videoSource: true,
      userMediaAudioConstraints: AUDIO_CONSTRAINTS,
      userMediaVideoConstraints: VIDEO_CONSTRAINTS,
    });

    // Cap the outgoing video so audio keeps its share of a weak uplink.
    try {
      await this.call.updateSendSettings({
        video: { maxQuality: "medium", encodings: { low: { maxBitrate: 200000 } } },
      });
    } catch (_) {
      /* non-fatal: the call is still fine without the cap */
    }

    return this.session;
  }

  /**
   * Start raw-tracks recording.
   *
   * This has to happen from a client: Daily's start_cloud_recording token
   * property only applies to "cloud" and "cloud-audio-only" modes, never to
   * raw-tracks. The coach triggers it, because the coach's token is the owner
   * and the coach is on the steadier device.
   *
   * Resolves true once Daily confirms recording began. Nothing is shown during
   * the call when it succeeds — only a failure is surfaced, so a session is
   * never lost silently while the call still feels ordinary.
   */
  async startRecording({ timeoutMs = 20000 } = {}) {
    if (!this.call) return false;

    const deadline = Date.now() + timeoutMs;
    let people = [];

    // Both participants must be present before recording can be framed on
    // each of them individually. The coach answers into a room the trainee is
    // already sitting in, so this normally resolves on the first check.
    while (Date.now() < deadline) {
      people = Object.values(this.call.participants() || {})
        .filter((p) => p && p.session_id);
      if (people.length >= 2) break;
      await new Promise((r) => setTimeout(r, 500));
    }
    if (people.length < 2) return false;

    let started = 0;
    for (const p of people) {
      const role = (p.user_name || "").toLowerCase().includes(ROLE_COACH)
        ? ROLE_COACH
        : ROLE_TRAINEE;
      try {
        await this.call.startRecording({
          type: "cloud",
          instanceId: INSTANCE_IDS[role],
          layout: { preset: "single-participant", session_id: p.session_id },
          // Record the camera's natural 16:9. Asking for a square here does
          // NOT frame square - Daily letterboxes the widescreen image inside
          // it, and those black bars then survive into the circular crop. The
          // renderer takes the centre square itself, which also keeps more
          // pixels on the face.
          width: 1280,
          height: 720,
        });
        started += 1;
      } catch (_) {
        /* try the other participant regardless */
      }
    }
    return started === 2;
  }

  async leave() {
    if (!this.call) return;
    try {
      await this.call.leave();
    } finally {
      this.call.destroy();
      this.call = null;
    }
  }

  setMic(on) {
    if (this.call) this.call.setLocalAudio(!!on);
  }

  setCam(on) {
    if (this.call) this.call.setLocalVideo(!!on);
  }
}
