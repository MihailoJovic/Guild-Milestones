/**
 * Guild Milestones - shared service (Google Apps Script)
 *
 * A tiny "notebook" that every officer's app checks in with, so only one app
 * announces at a time and they all share the same memory.
 *
 * SETUP: see SETUP.md. The only thing to edit is TOKEN, just below.
 */
const TOKEN = "REPLACE-ME-WITH-A-LONG-RANDOM-PASSWORD";
const LEASE_SECONDS = 180;   // an announcer who stops checking in loses the role after this long
const CHUNK = 2500;          // Script Properties values are limited in size, so big data is split up

function doGet() {
  return ContentService.createTextOutput("Guild Milestones shared service is running.");
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  try { lock.waitLock(20000); } catch (err) { return reply_({ ok: false, error: "busy, try again" }); }
  try {
    const req = JSON.parse((e && e.postData && e.postData.contents) || "{}");
    if (req.token !== TOKEN) return reply_({ ok: false, error: "wrong password" });
    switch (req.action) {
      case "status":  return reply_(status_());
      case "sync":    return reply_(sync_(req));
      case "commit":  return reply_(commit_(req));
      case "release": return reply_(release_(req));
      default:        return reply_({ ok: false, error: "unknown action" });
    }
  } catch (err) {
    return reply_({ ok: false, error: String(err) });
  } finally {
    lock.releaseLock();
  }
}

// --- who is the announcer? -------------------------------------------------
function sync_(req) {
  const now = Date.now();
  let lease = load_("lease") || {};
  const blocked = cleanBlocked_(lease.blocked, now);
  const held = !!lease.holder && lease.expires > now;
  let leader = false, reason = "";

  if (blocked[req.holder] > now) {
    reason = "cooling down";
  } else if (!held || lease.holder === req.holder) {
    lease = {
      holder: req.holder, name: req.name || "Officer", expires: now + LEASE_SECONDS * 1000,
      since: (held && lease.holder === req.holder) ? lease.since : now, blocked: blocked
    };
    save_("lease", lease);
    leader = true;
  }

  // keep the freshest game snapshot any officer has uploaded
  let snap = load_("snapshot");
  const up = req.snapshot;
  if (up && Array.isArray(up.members) && up.members.length && (!snap || up.updated > snap.updated)) {
    snap = up;
    save_("snapshot", snap);
  }

  const res = {
    ok: true, leader: leader, reason: reason, now: now,
    holder: held || leader ? lease.holder : "", leaderName: held || leader ? lease.name : "",
    expires: lease.expires || 0, snapshotTs: snap ? snap.updated : 0
  };
  if (leader) {
    const st = load_("state");
    const done = st ? (st.snap_ts || 0) : 0;
    res.stateVersion = st ? (st.version || 0) : 0;
    if (snap && (snap.updated > done || req.wantAll)) { res.snapshot = snap; res.state = st; }
  }
  return res;
}

// --- shared memory ----------------------------------------------------------
function commit_(req) {
  const now = Date.now();
  const lease = load_("lease") || {};
  if (lease.holder !== req.holder || lease.expires <= now) return { ok: false, error: "lost the announcer role" };
  const cur = load_("state");
  const curV = cur ? (cur.version || 0) : 0;
  if ((req.expectedVersion || 0) !== curV) return { ok: false, error: "version conflict", version: curV };
  const st = req.state || {};
  st.version = curV + 1;
  save_("state", st);
  lease.expires = now + LEASE_SECONDS * 1000;
  save_("lease", lease);
  return { ok: true, version: st.version };
}

// --- handing over -----------------------------------------------------------
function release_(req) {
  const now = Date.now();
  const lease = load_("lease") || {};
  const blocked = cleanBlocked_(lease.blocked, now);
  if (req.cooldownSeconds) blocked[req.holder] = now + req.cooldownSeconds * 1000;
  const mine = lease.holder === req.holder;
  save_("lease", {
    holder: mine ? "" : (lease.holder || ""), name: mine ? "" : (lease.name || ""),
    expires: mine ? 0 : (lease.expires || 0), since: 0, blocked: blocked
  });
  return { ok: true };
}

function status_() {
  const now = Date.now();
  const lease = load_("lease") || {};
  const held = !!lease.holder && lease.expires > now;
  const snap = load_("snapshot"), st = load_("state");
  return {
    ok: true, now: now, held: held, leaderName: held ? lease.name : "", expires: lease.expires || 0,
    snapshotTs: snap ? snap.updated : 0, members: snap ? snap.members.length : 0, stateVersion: st ? (st.version || 0) : 0
  };
}

// Run this by hand from the editor ONLY if you ever want to wipe the shared memory and start fresh.
function resetEverything() {
  PropertiesService.getScriptProperties().deleteAllProperties();
}

// --- helpers ------------------------------------------------------------------
function cleanBlocked_(b, now) {
  const out = {};
  Object.keys(b || {}).forEach(function (k) { if (b[k] > now) out[k] = b[k]; });
  return out;
}

function reply_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function load_(key) {
  const p = PropertiesService.getScriptProperties();
  const n = Number(p.getProperty(key + ".n") || 0);
  if (!n) return null;
  let s = "";
  for (let i = 0; i < n; i++) s += p.getProperty(key + "." + i) || "";
  try { return JSON.parse(s); } catch (err) { return null; }
}

function save_(key, obj) {
  const p = PropertiesService.getScriptProperties();
  const s = JSON.stringify(obj);
  const old = Number(p.getProperty(key + ".n") || 0);
  const parts = Math.max(1, Math.ceil(s.length / CHUNK));
  const set = {};
  set[key + ".n"] = String(parts);
  for (let i = 0; i < parts; i++) set[key + "." + i] = s.substr(i * CHUNK, CHUNK);
  p.setProperties(set);
  for (let i = parts; i < old; i++) p.deleteProperty(key + "." + i);
}
