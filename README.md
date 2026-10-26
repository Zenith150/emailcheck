# EmailCheck — Email Verification & Deliverability Diagnostics (v2.2)

EmailCheck is a full-stack, responsive web application designed for non-invasive email verification and deliverability diagnostics. It resolves cloud hosting restrictions—such as Render's outbound TCP port 25 block—by combining a local 7-stage diagnostic pipeline, an optional genuine SMTP recipient probing module (`smtp_probe.py`) with an intelligent circuit breaker, and reputable email verification APIs operating over secure HTTPS (port 443).

Addresses are classified into the three required assignment outcomes:
1. **Likely to be delivered** (Green) — Syntax valid, active mail routing, not disposable, and recipient inbox confirmed deliverable (via HTTPS provider or genuine SMTP 250 OK). Accompanied by a transparent disclaimer that server-level acceptance does not guarantee final inbox arrival (anti-spam filtering, mailbox quotas).
2. **Likely to bounce** (Red) — Malformed syntax, nonexistent domain (`NXDOMAIN`), RFC 7505 Null MX (`0 .`), domain without MX or A routing, explicit SMTP rejection (550), or confirmed undeliverable inbox.
3. **Unknown** (Slate) — Unverified recipient mailbox (when running in local mode without third-party API keys or when SMTP port 25 is blocked on cloud hosts like Render), catch-all mail servers (which accept any mailbox indiscriminately), disposable email domains (temporary/short-lived inboxes), DNS timeouts, nameserver errors, provider API rate limits (429), or temporary SMTP greylisting (450).

---

## Table of Contents

- [Live Demo & Repository Links](#live-demo--repository-links)
- [Render Outbound SMTP (Port 25) Restriction & Solution](#render-outbound-smtp-port-25-restriction--solution)
- [Genuine SMTP Probing Architecture (v2.2)](#genuine-smtp-probing-architecture-v22)
- [Key Features](#key-features)
- [Technology Stack](#technology-stack)
- [The 7-Stage Verification Pipeline](#the-7-stage-verification-pipeline)
- [Classification Criteria](#classification-criteria)
- [Supported Verification Providers & Setup](#supported-verification-providers--setup)
- [Environment Variables](#environment-variables)
- [Configuring Render Environment Variables](#configuring-render-environment-variables)
- [Privacy & Anti-Abuse Safeguards](#privacy--anti-abuse-safeguards)
- [Local Installation & Setup](#local-installation--setup)
- [Running Automated Tests](#running-automated-tests)
- [API Documentation](#api-documentation)
- [Production Deployment Guide](#production-deployment-guide)

---

## Live Demo & Repository Links

- **Live Application URL:** [https://emailcheck-7c9y.onrender.com/](https://emailcheck-7c9y.onrender.com/)
- **GitHub Repository URL:** [https://github.com/Zenith150/emailcheck](https://github.com/Zenith150/emailcheck)
- **Deployment Status:** **Active & Verified on Render** (`GET /health` → 200 OK, v2.2.0)
- **Project Submission Document:** [`submission/EmailCheck_Project_Submission.pdf`](submission/EmailCheck_Project_Submission.pdf)

---

## Render Outbound SMTP (Port 25) Restriction & Solution

### The Problem
Most modern cloud hosting platforms—including **Render**, AWS EC2 (by default), DigitalOcean, and Heroku—strictly block or filter outbound TCP traffic on **port 25** to protect their network reputations and prevent spam abuse. In standard architectures, attempting a raw SMTP handshake (`HELO` → `MAIL FROM` → `RCPT TO`) from a Render container results in immediate socket timeouts, connection drops, or false failure reporting.

Furthermore, cloud platforms **cannot** simply redirect recipient checks to submission ports (`587` or `465`). Ports 587/465 are reserved for authenticated user mail submission (`MSA`), which require account credentials. Recipient mail exchange servers (`MX`) only listen for unauthenticated inbound mail routing on **port 25**.

### The Production Solution
EmailCheck v2.2 solves this restriction cleanly and robustly without attempting to bypass network controls:

1. **Intelligent Port 25 Fallback & Fast Circuit Breaker:**
   Direct SMTP probing is optional and controlled by `ENABLE_SMTP_PROBE` (default `false`). When enabled on an environment where port 25 is filtered (such as Render), the built-in circuit breaker detects the network block on the first timeout and immediately marks subsequent probes in that batch as `unavailable`, preventing hanging requests or slow user response times.

2. **HTTPS Provider-Based Verification (Port 443):**
   When direct SMTP probing is blocked or disabled, EmailCheck utilizes reputable email verification REST APIs over standard HTTPS (port 443). The backend communicates with provider endpoints using Python standard library `urllib.request` with strict timeouts and resilient error handling.

3. **Modular Provider Architecture (`providers.py`):**
   The verification system defines a unified `BaseVerificationProvider` contract and includes out-of-the-box adapters for:
   - **Abstract API** (Default): Fast, recipient-level verification with deliverability scoring and catch-all detection.
   - **Hunter.io**: Industry-standard email verification with MX and SMTP status checks.
   - **ZeroBounce**: High-precision inbox validation and sub-status tagging.
   - **Local Fallback**: Zero-dependency local verification when no third-party API key is configured.

4. **Transparent Fallback & Honest Reporting:**
   - If no provider API key is configured and SMTP is unavailable, EmailCheck executes local syntax validation, domain normalization, disposable domain filtering, and DNS MX checks, while honestly classifying recipient inbox existence as unverified (`Unknown`) rather than falsely claiming inbox delivery or guessing invalidity.
   - If a provider exceeds rate limits or quota (HTTP 429), the system marks the recipient check as `Unknown` rather than crashing or returning false positives.

---

## Genuine SMTP Probing Architecture (v2.2)

EmailCheck v2.2 introduces a dedicated, production-grade SMTP probing module in [`smtp_probe.py`](smtp_probe.py). It provides real, protocol-compliant recipient verification on compatible hosting environments while gracefully degrading on restricted hosts like Render.

### Protocol Handshake Flow
```
Client (EmailCheck)                           Recipient MX Server (Port 25)
        │                                                    │
        ├────────────────── TCP Connect ────────────────────►│
        │◄──────────────── 220 Service Ready ────────────────┤
        ├────────────────── EHLO <hostname> ────────────────►│
        │◄──────────────── 250 OK ───────────────────────────┤
        ├────────────────── MAIL FROM:<sender> ──────────────►│
        │◄──────────────── 250 OK Sender OK ─────────────────┤
        ├────────────────── RCPT TO:<recipient> ─────────────►│
        │◄──────────────── 250 OK / 550 User Unknown ────────┤
        ├────────────────── RSET ────────────────────────────►│
        │◄──────────────── 250 OK Reset ─────────────────────┤
        ├────────────────── QUIT ────────────────────────────►│
        │◄──────────────── 221 Bye ──────────────────────────┤
```

### Strict Security & Safety Guarantees
- **NEVER ISSUES `DATA`:** EmailCheck **never** issues the SMTP `DATA` command. No message headers, subject lines, or body bytes are ever transmitted.
- **NEVER SENDS MESSAGES:** The protocol sequence is strictly limited to recipient probing and is always aborted cleanly with `RSET` and `QUIT`.
- **RFC 7505 Null MX Guard:** Domains with Null MX records (`0 .`) are rejected immediately before any network socket is opened.
- **Safe Circuit Breaker:** In environments where outbound port 25 is blocked (Render), the first socket timeout trips an in-memory circuit breaker, instantaneously marking subsequent addresses in the batch as `unavailable` to prevent timeouts.
- **Catch-All Domain Detection:** Probes a randomized non-existent address (`_emailcheck_verify_probe_test_@domain`) to verify whether the server accepts all recipients indiscriminately. Catch-all servers are safely classified as `inconclusive` (`Unknown`).
- **Response Sanitization:** All SMTP reply codes and messages are sanitized to strip CRLF control characters and bounded to 200 characters before inclusion in API or UI outputs.

---

## Key Features

- **Multi-Stage Verification Pipeline:**
  - RFC 5322 and RFC 5321 syntax validation.
  - Case-preserving email normalization (lowercase domain, preserve local part).
  - Built-in disposable email domain blacklist (200+ domains including Mailinator, GuerrillaMail, TempMail).
  - DNS resolution checking active MX records, `NXDOMAIN` existence, RFC 7505 Null MX (`0 .`), and RFC 5321 implicit MX fallback (A/AAAA).
  - Optional genuine SMTP recipient probing (`smtp_probe.py`) with Render fallback.
  - Provider-based recipient inbox deliverability over HTTPS (port 443).
- **Strict 3-Outcome Deliverability Classification:**
  - Addresses are strictly classified into **Likely to be delivered**, **Likely to bounce**, or **Unknown**.
  - Clearly differentiates between **domain mail routing** and **recipient mailbox existence**.
  - Conservatively treats SMTP 250 response as server-level recipient acceptance (warning that final downstream delivery is not guaranteed due to spam filters/quotas).
  - Classifies unverified recipient inboxes (when SMTP is unavailable/disabled and no provider key is configured) as **Unknown** with detailed, actionable diagnostics.
  - Marks temporary failures (SMTP 450 Greylisting) and catch-all servers as **Unknown**.
- **Batch Processing with Memoization:** Efficient in-memory caching prevents redundant DNS lookups and HTTP requests for duplicate domains and addresses within the same batch (up to 100 emails).
- **Modern Responsive Dashboard:**
  - Real-time address counter (up to 100 per batch).
  - Four summary metric cards: **Total**, **Likely to be Delivered**, **Likely to Bounce**, and **Unknown**.
  - Interactive filter tabs (All, Likely to Deliver, Likely to Bounce, Unknown) and real-time search box.
  - Sorting and pagination for large batches.
  - Collapsible per-row diagnostics showing DNS MX, HTTP Provider, and detailed SMTP Probe outputs.
  - Dedicated **Domain Diagnostics** lookup tool.
  - Local **Verification History** storing recent runs.
  - One-click RFC 4180 compliant **CSV Export** with all diagnostic and SMTP columns.
- **Production-Ready Backend:** Flask REST API with sliding-window rate limiting, input sanitization, health monitoring (`/health`), and WSGI production server (`gunicorn`).

---

## Technology Stack

- **Frontend:** HTML5, CSS3 (Custom Design System with responsive grid, accessible contrasts, and dark/light accents), Vanilla JavaScript (ES6+).
- **Backend:** Python 3.11, Flask 3.1.
- **Verification Engine:**
  - Syntax: `email-validator` with RFC 5322 regex fallback.
  - DNS / Routing: `dnspython` with public nameserver fallback (Google `8.8.8.8` / Cloudflare `1.1.1.1`).
  - SMTP Probing: Python `smtplib` and `socket` standard libraries (`smtp_probe.py`).
  - Recipient Verification: HTTPS REST API (Abstract API / Hunter / ZeroBounce) via Python `urllib.request`.
  - Disposable Detection: Curated dataset of 200+ known disposable and temporary email domains.
- **Production WSGI:** `gunicorn`.
- **Testing:** Python `unittest` suite (70 automated unit, integration, and mocking tests).
- **Documentation & PDF Generation:** ReportLab (`submission/EmailCheck_Project_Submission.pdf`).

---

## The 7-Stage Verification Pipeline

```
[ User Input (up to 100 emails) ]
             │
             ▼
[ Rate Limiter & Sanitizer ]
             │
             ▼
[ 1. Syntax Validation ] ─────────(Malformed)─────────► [ Likely to bounce ]
             │
          (Valid)
             ▼
[ 2. Normalization ] (trim whitespace, lowercase domain, preserve local part)
             │
             ▼
[ 3. Disposable Domain Check ] ───(Disposable Domain)─► [ Unknown ]
             │
        (Not Disposable)
             ▼
[ 4. DNS Domain Check ] ──────────(NXDOMAIN)──────────► [ Likely to bounce ]
             │                    (DNS Timeout/Error)─► [ Unknown ]
         (Exists)
             ▼
[ 5. MX Record Validation ]
             ├── RFC 7505 Null MX ("0 .") ────────────► [ Likely to bounce ]
             ├── No MX & No A/AAAA Record ────────────► [ Likely to bounce ]
             └── MX Found (or Implicit MX A/AAAA)
                        │
                        ▼
[ 6. Recipient Inbox Verification ]
             ├── Optional SMTP Probe (Port 25) ───► [ 250 OK -> Likely to be delivered / 550 -> Likely to bounce / 450 -> Unknown ]
             │   └── (If port 25 blocked or disabled, falls back cleanly to HTTPS provider)
             └── HTTPS Provider Check (Port 443)
                 ├── Undeliverable Mailbox ───────────► [ Likely to bounce ]
                 ├── Catch-All Server Detected ───────► [ Unknown ]
                 ├── Quota Exceeded / Rate Limit (429)► [ Unknown ]
                 ├── Network / API Timeout ───────────► [ Unknown ]
                 ├── No Provider Key Configured ──────► [ Unknown ] (Domain verified, inbox unverified)
                 └── Deliverable Mailbox ─────────────► [ Likely to be delivered ]
                        │
                        ▼
[ 7. Result Classification & Transparent Explanation ]
```

---

## Classification Criteria

| Classification | Badge | Meaning | Underlying Conditions |
| :--- | :--- | :--- | :--- |
| **Likely to be delivered** | <font color="#047857">**Likely to be Delivered**</font> | High confidence deliverability. | • RFC syntax is valid<br>• Domain exists with active MX routing<br>• Domain is not a known disposable provider<br>• Recipient accepted during genuine SMTP handshake (250 OK) OR confirmed deliverable via HTTPS provider API<br>*(Warning: Downstream inbox delivery is not guaranteed due to recipient spam filters or mailbox quotas)* |
| **Likely to bounce** | <font color="#b91c1c">**Likely to Bounce**</font> | Mail will bounce or be permanently rejected. | • Malformed syntax (missing `@`, consecutive dots, invalid characters)<br>• Nonexistent domain (`NXDOMAIN`)<br>• RFC 7505 Null MX record published (`0 .`)<br>• Domain has no MX and no A/AAAA records<br>• Remote server explicitly rejected recipient during SMTP handshake (550)<br>• Provider API confirmed recipient inbox does not exist |
| **Unknown** | <font color="#475569">**Unknown**</font> | Deliverability cannot be reliably determined. | • Domain MX routing is active, but specific recipient inbox existence could not be confirmed (SMTP probe unavailable on host and no HTTPS verification provider configured)<br>• Known disposable/temporary email domain (e.g. Mailinator)<br>• Catch-all mail server (accepts all addresses indiscriminately)<br>• DNS query timeout or DNS server failure (`SERVFAIL`)<br>• Temporary SMTP rejection (450 Greylisting)<br>• Hosting network blocked outbound port 25 (Render fallback)<br>• Provider API rate limit (HTTP 429) or monthly quota reached |

---

## Supported Verification Providers & Setup

EmailCheck supports multiple providers through standard environment variables:

### 1. Abstract API (Recommended Default)
- **Features:** Real-time deliverability checks, MX checks, SMTP verification, disposable detection, catch-all detection.
- **Free Tier:** 100 free requests per month.
- **Sign-up:** [https://app.abstractapi.com/users/signup](https://app.abstractapi.com/users/signup) → Select "Email Verification".
- **Render Configuration:**
  - `EMAIL_VERIFICATION_PROVIDER=abstract`
  - `EMAIL_VERIFICATION_API_KEY=<your_abstract_api_key>`

### 2. Hunter.io
- **Features:** Mailbox verification, SMTP checks, MX status, webmail detection.
- **Free Tier:** 25 free requests per month.
- **Sign-up:** [https://hunter.io/users/sign_up](https://hunter.io/users/sign_up)
- **Render Configuration:**
  - `EMAIL_VERIFICATION_PROVIDER=hunter`
  - `EMAIL_VERIFICATION_API_KEY=<your_hunter_api_key>`

### 3. ZeroBounce
- **Features:** Deep mailbox deliverability, spam trap detection, sub-status codes.
- **Free Tier:** 100 free requests per month.
- **Sign-up:** [https://www.zerobounce.net/members/signup/](https://www.zerobounce.net/members/signup/)
- **Render Configuration:**
  - `EMAIL_VERIFICATION_PROVIDER=zerobounce`
  - `EMAIL_VERIFICATION_API_KEY=<your_zerobounce_api_key>`

### 4. Local Fallback (No Key Required)
- If `EMAIL_VERIFICATION_API_KEY` is omitted or set to `local`, EmailCheck runs the complete local pipeline: syntax validation, normalization, 200+ disposable domain check, and DNS MX / Null MX checks.
- Recipient deliverability is safely classified as **Unknown** (unverified inbox), clearly distinguishing domain routing from recipient inbox confirmation without throwing errors or requiring API keys.

---

## Environment Variables

All settings are configured using standard environment variables (documented in [`.env.example`](.env.example)):

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `ENABLE_SMTP_PROBE` | boolean | `false` | Enable genuine SMTP recipient probing (`true`/`false`). Disabled by default for cloud hosts (Render) where port 25 is restricted. |
| `SMTP_PROBE_PORT` | integer | `25` | Target port for recipient mail server SMTP handshake. Standard mail exchange is port 25. |
| `SMTP_PROBE_TIMEOUT` | float | `5.0` | Socket timeout in seconds for SMTP probe connection and command responses. |
| `SMTP_HELO_HOSTNAME` | string | `mail.emailcheck.app` | FQDN sent in the SMTP EHLO/HELO greeting command. |
| `SMTP_PROBE_SENDER` | string | `verify@emailcheck.app` | Sender envelope address sent in the SMTP `MAIL FROM` command. |
| `EMAIL_VERIFICATION_PROVIDER` | string | `abstract` | Provider adapter to use: `abstract`, `hunter`, `zerobounce`, or `local`. |
| `EMAIL_VERIFICATION_API_KEY` | string | `""` | API key for the chosen provider. Stored server-side only; never sent to frontend. |
| `EMAIL_VERIFICATION_TIMEOUT` | float | `6.0` | HTTP request timeout in seconds for provider API calls. |
| `MAX_EMAILS_PER_REQUEST` | integer | `100` | Maximum email addresses allowed per verification batch. |
| `RATE_LIMIT_PER_MINUTE` | integer | `30` | Maximum batch requests per client IP per minute. |
| `PORT` | integer | `5000` | Server listening port (automatically set by Render). |

---

## Configuring Render Environment Variables

To add or update provider credentials on Render:

1. Log in to the [Render Dashboard](https://dashboard.render.com/).
2. Click on the **EmailCheck** web service (`emailcheck-7c9y`).
3. In the left navigation, click **Environment**.
4. Click **Add Environment Variable**:
   - Key: `EMAIL_VERIFICATION_PROVIDER` → Value: `abstract`
   - Key: `EMAIL_VERIFICATION_API_KEY` → Value: `<your_api_key_here>`
5. Click **Save Changes**. Render will automatically redeploy the service with the new credentials.
6. Verify by loading [https://emailcheck-7c9y.onrender.com/health](https://emailcheck-7c9y.onrender.com/health), which will report `"provider_configured": true`.

---

## Privacy & Anti-Abuse Safeguards

- **Zero Email Transmission:** EmailCheck **never sends emails**. It never issues the SMTP `DATA` command and never transmits any message headers or body content.
- **Server-Side API Key Isolation:** Third-party API keys are strictly kept in backend environment variables and never exposed to the frontend browser or client responses.
- **Zero Permanent Storage:** Submitted email lists are processed entirely in-memory and are never written to disk, databases, or third-party storage.
- **Privacy-First Logging:** Full email addresses are **never logged**. Server logs record only batch sizes, timestamps, and domain routing statuses.
- **Batch Limits & Throttling:** Requests are limited to a maximum of 100 email addresses per batch, protected by a sliding-window rate limiter (30 requests/minute per IP).
- **XSS Prevention:** All user inputs rendered in the frontend table and CSV exports are strictly sanitized and HTML-escaped.

---

## Local Installation & Setup

### Prerequisites
- Python 3.11+
- Git

### Installation Steps

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Zenith150/emailcheck.git
   cd emailcheck
   ```

2. **Create and activate a virtual environment:**
   ```bash
   # On Windows
   python -m venv venv
   .\venv\Scripts\activate

   # On macOS/Linux
   python3 -m venv venv
   source venv/bin/activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure environment variables (optional):**
   ```bash
   # Copy sample environment configuration
   cp .env.example .env
   # Edit .env with your preferred provider and API key
   ```

5. **Run the local development server:**
   ```bash
   python app.py
   ```

6. **Open your browser:**
   Navigate to [http://localhost:5000](http://localhost:5000)

---

## Running Automated Tests

The test suite contains **70 automated tests** covering syntax validation, normalization rules, disposable domain detection, mocked DNS MX resolution, RFC 7505 Null MX records, provider API integration adapters (Abstract, Hunter, ZeroBounce, Local), genuine SMTP probing protocol exchanges (`smtp_probe.py`), opt-in checkbox request extraction (`check_smtp` & `smtp_check`), server configuration security controls, circuit breaker tripping, catch-all detection, quota handling, the three assignment deliverability classifications (`Likely to be delivered`, `Likely to bounce`, `Unknown`), unverified mailbox shortened explanations, batch deduplication, and REST API endpoints.

To run the automated tests:
```bash
python -m unittest discover tests -v
```

All 70 tests run isolated from external network dependencies via unittest mocks and complete in under 2 seconds:
```
Ran 70 tests in 1.858s: OK
```

---

## API Documentation

### 1. Health Check
- **Endpoint:** `GET /health`
- **Method:** `GET`
- **Response:**
  ```json
  {
    "status": "healthy",
    "service": "EmailCheck",
    "version": "2.2.0",
    "provider": "abstract",
    "provider_configured": false,
    "smtp_outbound_available": false,
    "smtp_probe_config": {
      "enabled": false,
      "port": 25,
      "timeout": 5.0,
      "helo_hostname": "mail.emailcheck.app",
      "sender": "verify@emailcheck.app"
    },
    "pipeline_stage_count": 7,
    "pipeline_stages": [ ... ]
  }
  ```

### 2. Verify Email Batch
- **Endpoint:** `POST /api/verify`
- **Headers:** `Content-Type: application/json`
- **Request Body:**
  ```json
  {
    "emails": [
      "user@example.com",
      "temp@mailinator.com",
      "malformed..syntax@@domain",
      "user@nonexistent-domain-1234.org"
    ],
    "check_smtp": false
  }
  ```
- **Response:**
  ```json
  {
    "success": true,
    "total": 4,
    "summary": {
      "total": 4,
      "likely_to_deliver": 1,
      "likely_to_bounce": 2,
      "unknown": 1,
      "valid": 1,
      "invalid": 2,
      "risky": 0
    },
    "results": [
      {
        "email": "user@example.com",
        "normalized_email": "user@example.com",
        "syntax_valid": true,
        "domain": "example.com",
        "domain_status": "exists",
        "mx_status": "mx_found",
        "mx_records": [
          "mail.example.com (priority 10)"
        ],
        "is_null_mx": false,
        "disposable": false,
        "smtp_probe": {
          "smtp_status": "disabled",
          "smtp_attempted": false,
          "smtp_response_code": null,
          "smtp_response_message": null,
          "smtp_server": "mail.example.com",
          "smtp_duration_ms": 0.0,
          "smtp_explanation": "SMTP recipient probing is disabled by configuration (ENABLE_SMTP_PROBE=false)."
        },
        "recipient_check": {
          "status": "deliverable",
          "provider": "abstract",
          "details": "Inbox verified deliverable."
        },
        "classification": "Likely to be delivered",
        "outcome": "Likely to be delivered",
        "status_category": "valid",
        "reason": "Syntax valid, active MX routing verified, and recipient inbox confirmed deliverable via HTTPS provider.",
        "duration_ms": 42.1,
        "checked_at": "2026-10-26T21:25:00.000Z"
      }
    ]
  }
  ```

### 3. Domain Diagnostics
- **Endpoint:** `POST /api/domain` or `GET /api/domain?domain=example.com`
- **Response:**
  ```json
  {
    "success": true,
    "domain": "example.com",
    "domain_status": "exists",
    "mx_status": "mx_found",
    "is_null_mx": false,
    "is_disposable": false,
    "can_receive_email": true,
    "primary_mx": "mail.example.com",
    "mx_records": ["mail.example.com (priority 10)"],
    "verdict": "Ready to Receive Mail",
    "checked_at": "2026-10-26T21:25:00.000Z"
  }
  ```

---

## Production Deployment Guide

### Deploying to Render

1. **Option A: 1-Click Blueprint Deploy (Fastest):**
   - Click the [Deploy to Render](https://render.com/deploy?repo=https://github.com/Zenith150/emailcheck) button.
   - Render automatically reads [`render.yaml`](render.yaml) and provisions the service.

2. **Option B: Manual Dashboard Setup:**
   - Log in to the [Render Dashboard](https://dashboard.render.com/).
   - Click **New +** → **Web Service**.
   - Select repository `Zenith150/emailcheck`.
   - **Environment:** `Python`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT`
   - **Health Check Path:** `/health`
   *(Render will also detect `render.yaml` or `Procfile` automatically)*

3. **Verify Live Deployment:**
   - Open [https://emailcheck-7c9y.onrender.com/](https://emailcheck-7c9y.onrender.com/).
   - Verify that `/health` returns status code `200` ([https://emailcheck-7c9y.onrender.com/health](https://emailcheck-7c9y.onrender.com/health)).
   - Test address verification from the live dashboard.

---

## License

MIT License. Free for educational and commercial use.
