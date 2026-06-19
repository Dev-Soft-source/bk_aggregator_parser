# Persistent Identity Model

## Overview

Each residential proxy is permanently associated with a dedicated browser identity.

A browser identity consists of:

* Browser Fingerprint Profile
* Browser Profile Configuration
* Cookies
* localStorage
* sessionStorage
* Session Metadata

The purpose of this design is to maintain a stable and consistent browser identity for each proxy throughout its lifecycle.

---

# Identity Mapping

```text
Proxy-01
 ├─ Browser Profile-A
 ├─ Fingerprint-A
 └─ Session-A

Proxy-02
 ├─ Browser Profile-B
 ├─ Fingerprint-B
 └─ Session-B

Proxy-03
 ├─ Browser Profile-C
 ├─ Fingerprint-C
 └─ Session-C
```

Each proxy owns its own identity bundle.

Identity bundles should remain unchanged unless a manual reset or recovery procedure is explicitly performed.

---

# Identity Restoration Workflow

When a proxy is selected:

```text
Select Proxy
      ↓
Load Browser Profile
      ↓
Load Fingerprint Profile
      ↓
Restore Cookies
      ↓
Restore localStorage
      ↓
Restore sessionStorage
      ↓
Launch Browser
      ↓
Verify Session
      ↓
Connect WebSocket
```

---

# Design Objective

When a proxy is reused, the system automatically restores its associated browser fingerprint, browser profile, cookies, localStorage, and session data before reconnecting to Bet365.

This ensures that each proxy maintains a consistent browser identity throughout its lifecycle.

---

# Benefits

## Reduced Captcha Frequency

A stable browser identity reduces the likelihood of repeated verification challenges.

## Improved Session Stability

Existing sessions can be reused instead of creating new sessions after every rotation.

## Consistent Browser Fingerprint

Each proxy always presents the same browser characteristics.

## Improved WebSocket Reliability

Session continuity improves connection stability and reduces unnecessary reconnect events.

## Reduced Re-authentication

Previously established browser trust can be preserved.

## Higher Collector Uptime

Recovery operations become faster and less disruptive.

---

# Architecture Rule

A proxy should always reuse its assigned browser identity whenever possible.

```text
Proxy-01 → Identity-A

Proxy-02 → Identity-B

Proxy-03 → Identity-C
```

The system must avoid assigning a different fingerprint profile or session to an existing proxy unless one of the following occurs:

* Manual administrator reset
* Fingerprint profile corruption
* Session corruption
* Recovery procedure explicitly requires regeneration

---

# Browser Identity Components

## Browser Profile

Stores:

* Browser preferences
* User settings
* Browser state
* Persistent storage

## Fingerprint Profile

Stores:

* User-Agent
* Screen Resolution
* Timezone
* Language
* WebGL Profile
* Canvas Profile
* Hardware Profile

## Session Data

Stores:

* Cookies
* localStorage
* sessionStorage
* Authentication State

---

# Recovery Process

If a browser restart or proxy rotation occurs:

```text
Load Existing Identity
      ↓
Restore Browser Profile
      ↓
Restore Fingerprint Profile
      ↓
Restore Session Data
      ↓
Launch Browser
      ↓
Verify Session
      ↓
Reconnect WebSocket
      ↓
Resume Odds Collection
```

No new identity should be generated during normal operations.

---

# Success Criteria

* One browser identity per proxy
* One fingerprint profile per proxy
* One persistent session per proxy
* Identity automatically restored during rotation
* Identity automatically restored after browser restart
* Minimal captcha interruptions
* Stable WebSocket connectivity
* Consistent long-term browser behavior
* Improved 24/7 collector reliability

# proxy site: Decodo 
