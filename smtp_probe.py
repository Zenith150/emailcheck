"""
EmailCheck - Genuine SMTP Recipient Probing Module (v2.2)
Implements non-invasive, safe SMTP protocol handshakes (EHLO -> MAIL FROM -> RCPT TO -> RSET -> QUIT).
Never sends emails, never issues the SMTP DATA command, and respects network-level port 25 blocks
with an intelligent circuit-breaker to avoid hanging on restricted cloud environments like Render.
"""

import os
import re
import socket
import smtplib
import time
from typing import Dict, Any, Optional

# Circuit breaker flag: if outbound SMTP is determined to be completely blocked
# by the cloud host environment (e.g. Render port 25 restriction), do not repeatedly
# hang or retry every single address in the batch.
_circuit_breaker_active = False
_circuit_breaker_reason = "Outbound TCP port 25 is blocked or restricted on this hosting environment."


def reset_circuit_breaker() -> None:
    """Resets the circuit breaker state (useful for tests and dynamic configuration)."""
    global _circuit_breaker_active
    _circuit_breaker_active = False


def is_circuit_breaker_active() -> bool:
    """Returns True if the SMTP port 25 circuit breaker is tripped."""
    return _circuit_breaker_active


def get_smtp_probe_config() -> Dict[str, Any]:
    """
    Reads and validates SMTP probe settings from environment variables.
    Defaults to disabled (ENABLE_SMTP_PROBE=false).
    Note: Do not automatically convert port 25 to 587 or 465;
    submission ports do not support unauthenticated recipient probing against MX hosts.
    """
    raw_enabled = os.environ.get("ENABLE_SMTP_PROBE", "").strip().lower()
    enabled = raw_enabled in ("1", "true", "yes", "on")

    # Port configuration (strictly validate integer, default 25)
    raw_port = os.environ.get("SMTP_PROBE_PORT", "25").strip()
    try:
        port = int(raw_port)
        if not (1 <= port <= 65535):
            port = 25
    except ValueError:
        port = 25

    # Timeout configuration (default 5.0 seconds)
    raw_timeout = os.environ.get("SMTP_PROBE_TIMEOUT", "5").strip()
    try:
        timeout = float(raw_timeout)
        if timeout <= 0 or timeout > 30:
            timeout = 5.0
    except ValueError:
        timeout = 5.0

    # HELO / EHLO hostname
    helo_hostname = os.environ.get("SMTP_HELO_HOSTNAME", "").strip()
    if not helo_hostname:
        helo_hostname = "mail.emailcheck.app"

    # Sender address for MAIL FROM
    sender = os.environ.get("SMTP_PROBE_SENDER", "").strip()
    if not sender or "@" not in sender:
        sender = "verify@emailcheck.app"

    return {
        "enabled": enabled,
        "port": port,
        "timeout": timeout,
        "helo_hostname": helo_hostname,
        "sender": sender
    }


def is_smtp_probe_enabled() -> bool:
    """Returns True if SMTP probing is explicitly enabled via environment variables."""
    return get_smtp_probe_config()["enabled"]


def sanitize_smtp_message(message: Any, max_len: int = 200) -> str:
    """
    Sanitizes SMTP response messages:
    - Strips non-printable ASCII and control characters (CRLF, tabs).
    - Prevents XSS or raw terminal escape sequences.
    - Truncates to max_len.
    """
    if message is None:
        return ""
    if isinstance(message, bytes):
        try:
            msg_str = message.decode("utf-8", errors="replace")
        except Exception:
            msg_str = str(message)
    else:
        msg_str = str(message)

    # Replace newlines and carriage returns with spaces
    cleaned = re.sub(r"[\r\n\t]+", " ", msg_str)
    # Strip any control characters (< ASCII 32 or == 127)
    cleaned = "".join(ch for ch in cleaned if 32 <= ord(ch) < 127)
    cleaned = cleaned.strip()

    if len(cleaned) > max_len:
        return cleaned[:max_len] + "..."
    return cleaned


def probe_smtp_recipient(
    email: str,
    mx_host: Optional[str],
    port: Optional[int] = None,
    timeout: Optional[float] = None,
    helo_hostname: Optional[str] = None,
    sender: Optional[str] = None,
    smtp_client_class=smtplib.SMTP
) -> Dict[str, Any]:
    """
    Executes a genuine, non-invasive SMTP recipient probe:
    1. Connects to the MX server on configured port.
    2. Reads initial greeting.
    3. Sends EHLO (falls back to HELO).
    4. Sends MAIL FROM:<sender>.
    5. Sends RCPT TO:<email>.
    6. Sends RSET and terminates with QUIT.
    
    CRITICAL: Never issues DATA, never sends email bodies.
    
    Returns structured dictionary:
        - smtp_status: "accepted" | "rejected" | "inconclusive" | "unavailable" | "disabled"
        - smtp_attempted: bool
        - smtp_response_code: int or None
        - smtp_response_message: str or None
        - smtp_server: str or None
        - smtp_duration_ms: float or None
        - smtp_explanation: str
    """
    global _circuit_breaker_active

    config = get_smtp_probe_config()
    target_port = port if port is not None else config["port"]
    target_timeout = timeout if timeout is not None else config["timeout"]
    target_helo = helo_hostname or config["helo_hostname"]
    target_sender = sender or config["sender"]

    result = {
        "smtp_status": "disabled",
        "smtp_attempted": False,
        "smtp_response_code": None,
        "smtp_response_message": None,
        "smtp_server": mx_host,
        "smtp_duration_ms": 0.0,
        "smtp_explanation": "SMTP recipient probing is disabled by configuration (ENABLE_SMTP_PROBE=false)."
    }

    # 1. Check if SMTP probing is globally enabled
    if not config["enabled"]:
        return result

    # 2. Check if circuit breaker is active (host blocks port 25)
    if _circuit_breaker_active:
        result["smtp_status"] = "unavailable"
        result["smtp_attempted"] = False
        result["smtp_explanation"] = (
            f"SMTP probe skipped: {_circuit_breaker_reason} "
            "(Circuit breaker active for current process to prevent request delays)."
        )
        return result

    # 3. Check for valid MX host
    if not mx_host or not isinstance(mx_host, str) or not mx_host.strip():
        result["smtp_status"] = "unavailable"
        result["smtp_attempted"] = False
        result["smtp_explanation"] = "No valid MX mail server host available for SMTP recipient probe."
        return result

    clean_mx = mx_host.strip().rstrip(".")

    # 4. Check for RFC 7505 Null MX before connecting
    if clean_mx in ("", ".", "0 ."):
        result["smtp_status"] = "rejected"
        result["smtp_attempted"] = False
        result["smtp_explanation"] = "Domain publishes RFC 7505 Null MX ('0 .'). Connecting aborted as domain explicitly refuses all mail."
        return result

    # 5. Connect and execute safe SMTP handshake
    start_time = time.perf_counter()
    result["smtp_attempted"] = True
    result["smtp_server"] = clean_mx
    client = None

    try:
        # Instantiate client with bounded timeout
        client = smtp_client_class(timeout=target_timeout)
        
        # Connect to MX host
        code, resp = client.connect(clean_mx, target_port)
        sanitized_greeting = sanitize_smtp_message(resp)

        if code >= 400:
            result["smtp_status"] = "unavailable" if code >= 500 else "inconclusive"
            result["smtp_response_code"] = code
            result["smtp_response_message"] = sanitized_greeting
            result["smtp_explanation"] = f"Mail server rejected connection greeting with code {code}: {sanitized_greeting}"
            return result

        # Send EHLO (or fallback to HELO)
        try:
            ehlo_code, ehlo_resp = client.ehlo(target_helo)
            if ehlo_code >= 400:
                client.helo(target_helo)
        except Exception:
            try:
                client.helo(target_helo)
            except Exception as helo_err:
                result["smtp_status"] = "inconclusive"
                result["smtp_explanation"] = f"SMTP HELO/EHLO negotiation failed: {sanitize_smtp_message(helo_err)}"
                return result

        # Issue MAIL FROM
        mail_code, mail_resp = client.mail(target_sender)
        sanitized_mail_resp = sanitize_smtp_message(mail_resp)

        if mail_code >= 400:
            result["smtp_status"] = "inconclusive"
            result["smtp_response_code"] = mail_code
            result["smtp_response_message"] = sanitized_mail_resp
            result["smtp_explanation"] = f"Mail server rejected sender address during MAIL FROM ({mail_code}): {sanitized_mail_resp}"
            return result

        # Issue RCPT TO for the recipient address
        rcpt_code, rcpt_resp = client.rcpt(email)
        sanitized_rcpt = sanitize_smtp_message(rcpt_resp)
        result["smtp_response_code"] = rcpt_code
        result["smtp_response_message"] = sanitized_rcpt

        # Conservative response interpretation:
        if rcpt_code in (250, 251):
            # 250 OK: Recipient accepted for delivery during this session.
            # Perform optional catch-all check with a randomized probe to avoid false positives
            is_catch_all = False
            domain_part = email.split("@")[-1] if "@" in email else ""
            if domain_part:
                probe_fake_email = f"smtp_probe_nonexistent_check_987x@{domain_part}"
                try:
                    probe_code, _ = client.rcpt(probe_fake_email)
                    if probe_code in (250, 251):
                        is_catch_all = True
                except Exception:
                    pass

            if is_catch_all:
                result["smtp_status"] = "inconclusive"
                result["smtp_explanation"] = (
                    f"Mail server returned {rcpt_code} OK, but accepted a randomized invalid mailbox. "
                    "Domain is configured as catch-all; individual mailbox existence cannot be proven."
                )
            else:
                result["smtp_status"] = "accepted"
                result["smtp_explanation"] = (
                    f"Recipient accepted by server during SMTP handshake (code {rcpt_code}: {sanitized_rcpt}). "
                    "Note: Confirms address acceptance at the MX host; does not guarantee inbox delivery due to mailbox quotas or anti-spam filtering."
                )

        elif rcpt_code in (550, 551, 552, 553, 554):
            # Permanent recipient rejection specifically from the remote MX server
            result["smtp_status"] = "rejected"
            result["smtp_explanation"] = f"Mail server explicitly rejected recipient address (code {rcpt_code}: {sanitized_rcpt})."

        elif rcpt_code in (421, 450, 451, 452):
            # Temporary server failure, rate limit, or greylisting
            result["smtp_status"] = "inconclusive"
            result["smtp_explanation"] = (
                f"Temporary SMTP response or greylisting encountered (code {rcpt_code}: {sanitized_rcpt}). "
                "Mail server requested a retry later; mailbox existence is inconclusive."
            )

        elif rcpt_code == 252:
            # 252: Cannot verify recipient, but will accept message and attempt delivery
            result["smtp_status"] = "inconclusive"
            result["smtp_explanation"] = (
                f"Mail server returned code 252 ({sanitized_rcpt}): Server policy refuses to disclose mailbox existence "
                "prior to message transmission."
            )

        else:
            result["smtp_status"] = "inconclusive"
            result["smtp_explanation"] = f"Received unexpected SMTP response code {rcpt_code}: {sanitized_rcpt}"

        # Clean reset (never DATA!)
        try:
            client.rset()
        except Exception:
            pass

        return result

    except (socket.timeout, TimeoutError):
        # Socket timed out
        # If this is port 25 and it timed out, trip the circuit breaker on cloud hosts
        if target_port == 25:
            _circuit_breaker_active = True
        result["smtp_status"] = "unavailable"
        result["smtp_explanation"] = (
            f"SMTP connection to {clean_mx}:{target_port} timed out after {target_timeout}s. "
            "Outbound SMTP port 25 is restricted or firewalled on this hosting environment (e.g. Render network security policy)."
        )
        return result

    except (ConnectionRefusedError, socket.error, OSError) as conn_err:
        err_msg = str(conn_err)
        if target_port == 25:
            _circuit_breaker_active = True
        result["smtp_status"] = "unavailable"
        result["smtp_explanation"] = (
            f"SMTP connection to {clean_mx}:{target_port} failed: {sanitize_smtp_message(err_msg)}. "
            "Outbound port 25 is blocked or unreachable."
        )
        return result

    except smtplib.SMTPException as smtp_err:
        result["smtp_status"] = "inconclusive"
        result["smtp_explanation"] = f"SMTP protocol error: {sanitize_smtp_message(str(smtp_err))}"
        return result

    except Exception as exc:
        result["smtp_status"] = "inconclusive"
        result["smtp_explanation"] = f"Unexpected error during SMTP probe: {sanitize_smtp_message(str(exc))}"
        return result

    finally:
        result["smtp_duration_ms"] = round((time.perf_counter() - start_time) * 1000, 1)
        if client:
            try:
                client.quit()
            except Exception:
                try:
                    client.close()
                except Exception:
                    pass
