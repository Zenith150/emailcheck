"""
EmailCheck - Verification Core Logic (v2.1)
Implements an authoritative 7-stage non-invasive email verification pipeline:
1. Syntax Validation (RFC 5322)
2. Normalization (preserves local-part, normalizes domain)
3. Disposable Email Detection (curated dataset & provider tags)
4. DNS Resolution & Domain Validation
5. MX Record Validation (including RFC 7505 Null MX & RFC 5321 Implicit MX)
6. Provider-based HTTPS Inbox Verification (Abstract, Hunter, ZeroBounce, or Local Fallback)
7. Result Classification (Valid, Invalid, Risky, Unknown)
"""

import os
import re
import socket
import smtplib
import time
import datetime
from typing import Dict, Any, List, Optional, Tuple
import dns.resolver
import dns.exception

try:
    import email_validator
    from email_validator import validate_email as ext_validate_email, EmailNotValidError
    HAS_EMAIL_VALIDATOR = True
except ImportError:
    HAS_EMAIL_VALIDATOR = False

from providers import is_disposable_domain, get_verification_provider, BaseVerificationProvider

# Authoritative definition of the 7 pipeline stages
PIPELINE_STAGES = [
    {
        "id": 1,
        "name": "Syntax Validation",
        "description": "Validates email structure and characters according to RFC 5322 standards."
    },
    {
        "id": 2,
        "name": "Email Normalization",
        "description": "Trims whitespace and lowercases domain while preserving local-part casing per RFC 5321."
    },
    {
        "id": 3,
        "name": "Disposable Domain Detection",
        "description": "Identifies temporary or disposable email domains using a curated blacklist and provider tags."
    },
    {
        "id": 4,
        "name": "DNS Domain Validation",
        "description": "Resolves domain records in DNS and detects nonexistent domains (NXDOMAIN)."
    },
    {
        "id": 5,
        "name": "MX and Null MX Validation",
        "description": "Queries mail routing records, detects RFC 7505 Null MX ('0 .'), and applies implicit MX fallbacks."
    },
    {
        "id": 6,
        "name": "Provider Recipient Verification",
        "description": "Performs HTTPS recipient inbox deliverability check via configured provider over port 443."
    },
    {
        "id": 7,
        "name": "Result Classification",
        "description": "Classifies addresses into Valid, Invalid, Risky, or Unknown with diagnostic reasoning."
    }
]

# Reliable fallback nameservers to avoid local/virtual adapter timeouts
PUBLIC_NAMESERVERS = ['8.8.8.8', '1.1.1.1', '8.8.4.4', '1.0.0.1']

# RFC 5322 compliant regex for secondary validation
EMAIL_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+"
    r"@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)


def get_configured_resolver(timeout: float = 3.5) -> dns.resolver.Resolver:
    """
    Creates and returns a dnspython Resolver configured with public nameservers
    and strict lifetime timeouts to prevent hanging requests.
    """
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = PUBLIC_NAMESERVERS
    resolver.lifetime = timeout
    resolver.timeout = timeout
    return resolver


def normalize_email(email_str: str) -> Tuple[str, str, str]:
    """
    Normalizes an email address:
    - Trims leading/trailing whitespace.
    - Lowers domain part and strips trailing dots.
    - Preserves local-part casing per RFC 5321 (do not lowercase local-part).
    Returns (local_part, normalized_domain, normalized_full_email).
    """
    cleaned = str(email_str or "").strip()
    if "@" in cleaned:
        parts = cleaned.split("@", 1)
        local_part = parts[0]
        domain = parts[1].strip().lower().rstrip(".")
        normalized_full = f"{local_part}@{domain}"
        return local_part, domain, normalized_full
    return cleaned, "", cleaned


def validate_syntax(email: str) -> Tuple[bool, str, str, Optional[str]]:
    """
    Stage 1 & 2: Validates email syntax against RFC standards and normalizes domain.
    Returns:
        (is_valid: bool, local_part: str, normalized_domain: str, error_message: Optional[str])
    """
    if not email or not isinstance(email, str):
        return False, "", "", "Email address is empty or not a valid string."

    raw = email.strip()
    if len(raw) > 254:
        return False, "", "", "Email exceeds maximum RFC length of 254 characters."

    if "@" not in raw:
        return False, "", "", "Missing '@' symbol in email address."

    parts = raw.split("@")
    if len(parts) != 2:
        return False, "", "", "Email contains multiple '@' symbols."

    local_part, raw_domain = parts[0], parts[1]

    if not local_part:
        return False, "", raw_domain, "Missing local part before '@'."
    if len(local_part) > 64:
        return False, local_part, raw_domain, "Local part exceeds 64 characters."
    if local_part.startswith(".") or local_part.endswith("."):
        return False, local_part, raw_domain, "Local part cannot start or end with a dot."
    if ".." in local_part:
        return False, local_part, raw_domain, "Local part cannot contain consecutive dots ('..')."

    domain = raw_domain.strip().lower().rstrip(".")
    if not domain:
        return False, local_part, "", "Missing domain part after '@'."
    if len(domain) > 253:
        return False, local_part, domain, "Domain exceeds 253 characters."
    if ".." in domain:
        return False, local_part, domain, "Domain cannot contain consecutive dots ('..')."
    if "." not in domain:
        return False, local_part, domain, "Domain must contain a valid top-level domain (TLD)."

    tld = domain.split(".")[-1]
    if len(tld) < 2:
        return False, local_part, domain, "Top-level domain (TLD) must be at least 2 characters."

    # Validate with email-validator library if installed
    if HAS_EMAIL_VALIDATOR:
        try:
            val = ext_validate_email(raw, check_deliverability=False)
            norm_domain = val.domain.lower().rstrip(".")
            return True, val.local_part, norm_domain, None
        except EmailNotValidError as err:
            return False, local_part, domain, str(err)
        except Exception as ex:
            return False, local_part, domain, f"Syntax validation failed: {str(ex)}"

    # Regex fallback
    if not EMAIL_REGEX.match(raw):
        return False, local_part, domain, "Email format does not adhere to RFC 5322 syntax."

    return True, local_part, domain, None


def check_domain_dns(
    domain: str,
    resolver: Optional[dns.resolver.Resolver] = None,
    timeout: float = 3.5
) -> Dict[str, Any]:
    """
    Stage 4 & 5: Checks DNS records for the domain:
    1. Query MX records.
    2. Check for RFC 7505 Null MX record ('0 .').
    3. Fallback to A/AAAA records (RFC 5321 Implicit MX) if no MX is found.
    Handles NXDOMAIN, timeouts, and missing records.
    """
    res = resolver or get_configured_resolver(timeout=timeout)
    domain_clean = domain.strip().lower().rstrip(".")

    # Handle IDNA encoding for internationalized domains
    try:
        domain_ascii = domain_clean.encode("idna").decode("ascii")
    except Exception:
        domain_ascii = domain_clean

    result = {
        "domain": domain_clean,
        "domain_status": "unknown",  # "exists", "nonexistent", "dns_timeout", "dns_error"
        "mx_status": "unknown",      # "mx_found", "implicit_mx_found", "null_mx", "no_records", "none", "dns_error"
        "mx_records": [],            # List of formatted records
        "primary_mx": None,          # Hostname of highest priority MX
        "is_null_mx": False,         # RFC 7505 Null MX flag
        "error": None
    }

    # Step 1: Query MX records
    try:
        mx_answers = res.resolve(domain_ascii, "MX")
        sorted_mx = sorted(mx_answers, key=lambda r: r.preference)

        # Check for RFC 7505 Null MX record
        for r in sorted_mx:
            host_clean = str(r.exchange).strip().rstrip(".")
            # RFC 7505: single MX with priority 0 and host "." or empty
            if host_clean == "" or host_clean == ".":
                result["domain_status"] = "exists"
                result["mx_status"] = "null_mx"
                result["is_null_mx"] = True
                result["mx_records"] = ["0 . (RFC 7505 Null MX: Domain explicitly does not accept email)"]
                result["error"] = "Domain publishes an RFC 7505 Null MX record ('0 .'), explicitly declaring that it does not accept email."
                return result

        records_list = []
        for r in sorted_mx:
            host = str(r.exchange).rstrip(".")
            records_list.append(f"{host} (priority {r.preference})")

        result["domain_status"] = "exists"
        result["mx_status"] = "mx_found"
        result["mx_records"] = records_list
        result["primary_mx"] = str(sorted_mx[0].exchange).rstrip(".") if sorted_mx else None
        return result

    except dns.resolver.NXDOMAIN:
        # Domain does not exist in DNS
        result["domain_status"] = "nonexistent"
        result["mx_status"] = "none"
        result["error"] = "Domain does not exist in DNS (NXDOMAIN)."
        return result

    except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
        # MX record not present; RFC 5321 Section 5.1 Fallback to Address records (Implicit MX)
        try:
            a_answers = res.resolve(domain_ascii, "A")
            ip_list = [str(a) for a in a_answers]
            result["domain_status"] = "exists"
            result["mx_status"] = "implicit_mx_found"
            result["mx_records"] = [f"{domain_clean} (Implicit MX via A record: {', '.join(ip_list[:2])})"]
            result["primary_mx"] = domain_ascii
            return result
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            try:
                aaaa_answers = res.resolve(domain_ascii, "AAAA")
                ipv6_list = [str(a) for a in aaaa_answers]
                result["domain_status"] = "exists"
                result["mx_status"] = "implicit_mx_found"
                result["mx_records"] = [f"{domain_clean} (Implicit MX via AAAA record: {', '.join(ipv6_list[:2])})"]
                result["primary_mx"] = domain_ascii
                return result
            except Exception:
                result["domain_status"] = "exists"
                result["mx_status"] = "no_records"
                result["error"] = "Domain exists, but has no MX, A, or AAAA mail routing records."
                return result
        except (dns.resolver.LifetimeTimeout, dns.resolver.Timeout):
            result["domain_status"] = "dns_timeout"
            result["mx_status"] = "dns_timeout"
            result["error"] = "DNS query timed out during A/AAAA record fallback."
            return result
        except Exception as e:
            result["domain_status"] = "dns_error"
            result["mx_status"] = "dns_error"
            result["error"] = f"DNS fallback error: {str(e)}"
            return result

    except (dns.resolver.LifetimeTimeout, dns.resolver.Timeout):
        result["domain_status"] = "dns_timeout"
        result["mx_status"] = "dns_timeout"
        result["error"] = "DNS resolution timed out while querying MX records."
        return result

    except Exception as e:
        result["domain_status"] = "dns_error"
        result["mx_status"] = "dns_error"
        result["error"] = f"DNS query failed: {str(e)}"
        return result


def test_smtp_outbound_capability(host: str = "aspmx.l.google.com", port: int = 25, timeout: float = 2.0) -> bool:
    """
    Tests if outbound port 25 connections can be established from the current host.
    Used for health checks and environment capability reporting.
    """
    s = None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        res = s.connect_ex((host, port))
        return res == 0
    except Exception:
        return False
    finally:
        if s:
            try:
                s.close()
            except Exception:
                pass


def check_smtp_recipient(
    email: str,
    mx_host: str,
    sender: str = "verify@emailcheck.app",
    timeout: float = 3.5
) -> Dict[str, Any]:
    """
    Optional direct SMTP check for non-restricted hosting environments.
    Disabled by default on Render and cloud hosts where port 25 is restricted.
    Never sends emails or issues SMTP DATA command.
    """
    result = {
        "smtp_attempted": True,
        "smtp_status": "unknown",
        "code": None,
        "is_catch_all": False,
        "reason": None
    }

    if not mx_host:
        result["smtp_attempted"] = False
        result["smtp_status"] = "skipped"
        result["reason"] = "No MX host available for direct SMTP."
        return result

    smtp_client = None
    try:
        smtp_client = smtplib.SMTP(timeout=timeout)
        code, resp = smtp_client.connect(mx_host, 25)
        if code >= 400:
            result["smtp_status"] = "connection_failed"
            result["code"] = code
            result["reason"] = f"Mail server rejected connection with code {code}."
            return result

        smtp_client.ehlo_or_helo_if_needed()
        code, resp = smtp_client.mail(sender)
        if code >= 400:
            result["smtp_status"] = "unverified"
            result["code"] = code
            result["reason"] = f"Server rejected MAIL FROM ({code})."
            return result

        code, resp = smtp_client.rcpt(email)
        result["code"] = code

        if code == 250:
            domain = email.split("@")[-1]
            probe_email = f"nonexistent_probe_check_7921x@{domain}"
            try:
                p_code, _ = smtp_client.rcpt(probe_email)
                if p_code == 250:
                    result["smtp_status"] = "catch_all"
                    result["is_catch_all"] = True
                    result["reason"] = "Domain mail server is configured as catch-all."
                    return result
            except Exception:
                pass

            result["smtp_status"] = "mailbox_accepted"
            result["reason"] = "Mail server accepted recipient in SMTP handshake (250 OK)."
            return result

        elif code in (550, 551, 552, 553, 554):
            result["smtp_status"] = "mailbox_rejected"
            result["reason"] = f"Mail server explicitly rejected address ({code})."
            return result

        elif code in (421, 450, 451, 452):
            result["smtp_status"] = "temporary_failure"
            result["reason"] = f"Temporary mail server response / greylisting ({code})."
            return result
        else:
            result["smtp_status"] = "unknown"
            result["reason"] = f"Inconclusive SMTP response code {code}."
            return result

    except (socket.timeout, TimeoutError):
        result["smtp_status"] = "timeout"
        result["reason"] = "Direct SMTP connection timed out (port 25 restricted or host unreachable)."
        return result
    except (ConnectionRefusedError, socket.error, OSError) as err:
        result["smtp_status"] = "connection_failed"
        result["reason"] = f"Direct SMTP connection failed (port 25 restricted): {str(err)}"
        return result
    except Exception as err:
        result["smtp_status"] = "unknown"
        result["reason"] = f"SMTP error: {str(err)}"
        return result
    finally:
        if smtp_client:
            try:
                smtp_client.quit()
            except Exception:
                try:
                    smtp_client.close()
                except Exception:
                    pass


def classify_result(
    syntax_valid: bool,
    domain_status: str,
    mx_status: str,
    is_disposable: bool,
    provider_res: Optional[Dict[str, Any]] = None,
    smtp_info: Optional[Dict[str, Any]] = None,
    syntax_error: Optional[str] = None,
    domain_error: Optional[str] = None
) -> Tuple[str, str, str]:
    """
    Stage 7: Transparent, multi-factor result classification.
    Returns:
        (classification: str, status_category: str, explanation: str)
    Classifications:
        - "Valid" / "Likely to be Delivered": Valid syntax, domain exists, MX valid, not disposable, recipient verified.
        - "Invalid" / "Likely to Bounce": Syntax invalid, NXDOMAIN, Null MX, no MX/A records, or mailbox confirmed invalid.
        - "Risky": Disposable domain, catch-all server, role-based email, or domain valid but recipient unverified.
        - "Unknown": DNS timeout, DNS error, provider timeout, or quota exceeded.
    """
    # 1. Syntax Check
    if not syntax_valid:
        msg = f"Invalid email syntax: {syntax_error or 'malformed structure'}."
        return "Invalid", "invalid", msg

    # 2. Domain / DNS Checks
    if domain_status == "nonexistent":
        return "Invalid", "invalid", "The domain does not exist in DNS (NXDOMAIN). Mail sent to this address will bounce."

    # 3. RFC 7505 Null MX Check
    if mx_status == "null_mx":
        return "Invalid", "invalid", "Domain publishes an RFC 7505 Null MX record ('0 .'), explicitly declaring that it does not accept email."

    # 4. Missing Mail Routing
    if mx_status == "no_records":
        return "Invalid", "invalid", "Domain exists, but has no MX or A records configured to receive email."

    # 5. DNS Errors / Timeouts
    if domain_status in ("dns_timeout", "dns_error") or mx_status in ("dns_timeout", "dns_error"):
        return "Unknown", "unknown", f"DNS query could not be completed ({domain_error or 'timeout/server failure'})."

    # 6. Disposable Email Check
    if is_disposable:
        return "Risky", "risky", "Domain belongs to a known temporary/disposable email service (e.g., mailinator.com). These inboxes are short-lived and risky for deliverability."

    # 7. Provider-Based Inbox Verification (HTTPS)
    if provider_res:
        p_status = provider_res.get("status")
        p_reason = provider_res.get("reason", "")
        p_disposable = provider_res.get("is_disposable")
        p_catchall = provider_res.get("is_catch_all")

        if p_disposable:
            return "Risky", "risky", "Verification provider flagged domain as a temporary or disposable email address."

        if p_status == "deliverable":
            return "Valid", "valid", f"Syntax valid, active MX routing verified, and recipient inbox confirmed deliverable ({p_reason})."

        elif p_status == "undeliverable":
            return "Invalid", "invalid", f"Recipient inbox confirmed invalid or undeliverable ({p_reason})."

        elif p_status == "risky" or p_catchall:
            return "Risky", "risky", f"Address flagged as risky ({p_reason})."

        elif p_status == "unavailable":
            # Provider is unconfigured (Local engine): domain is valid, but recipient inbox is unverified
            return "Risky", "risky", (
                "Domain mail routing is active (MX verified). Recipient-level verification is unverified because no provider API key is configured. "
                "Note: A valid domain does not guarantee individual recipient inbox existence."
            )

        elif p_status == "unknown":
            return "Unknown", "unknown", f"Recipient inbox verification was inconclusive ({p_reason})."

    # 8. Optional Direct SMTP Check (if enabled and attempted)
    if smtp_info and smtp_info.get("smtp_attempted"):
        smtp_status = smtp_info.get("smtp_status")
        smtp_reason = smtp_info.get("reason", "")
        is_catch_all = smtp_info.get("is_catch_all", False)

        if smtp_status == "mailbox_rejected":
            return "Invalid", "invalid", f"Mail server explicitly rejected mailbox: {smtp_reason}."
        if smtp_status == "catch_all" or is_catch_all:
            return "Risky", "risky", "Domain server is configured as catch-all (accepts any mailbox). Individual mailbox existence cannot be confirmed."
        if smtp_status in ("connection_failed", "timeout"):
            return "Unknown", "unknown", "Outbound direct SMTP connection was blocked or timed out (standard mail port 25 restricted on hosting platform). Mail routing is valid, but specific mailbox existence cannot be confirmed."
        if smtp_status == "mailbox_accepted":
            return "Valid", "valid", "Syntax valid, MX routing verified, and mail server accepted recipient in SMTP handshake."

    # 9. Fallback if no provider and no SMTP attempted:
    # Explicitly distinguish domain-level validation from recipient-level verification!
    return "Risky", "risky", (
        "Valid syntax and active MX routing verified. Recipient inbox verification is unverified. "
        "Domain is prepared to receive mail, but recipient existence cannot be guaranteed without HTTPS provider verification."
    )


def verify_single_email(
    email_str: str,
    resolver: Optional[dns.resolver.Resolver] = None,
    provider: Optional[BaseVerificationProvider] = None,
    perform_smtp: bool = False,
    domain_cache: Optional[Dict[str, Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Performs complete 7-stage verification pipeline for a single email address.
    """
    start_t = time.perf_counter()
    raw_email = str(email_str or "").strip()
    local_part, norm_domain, normalized_email = normalize_email(raw_email)

    # Stage 1 & 2: Syntax validation
    syntax_valid, _, domain, syntax_err = validate_syntax(raw_email)

    if not syntax_valid:
        classification, status_cat, reason = classify_result(
            syntax_valid=False,
            domain_status="untested",
            mx_status="untested",
            is_disposable=False,
            syntax_error=syntax_err
        )
        duration_ms = round((time.perf_counter() - start_t) * 1000, 1)
        return {
            "email": raw_email,
            "normalized_email": normalized_email,
            "syntax_valid": False,
            "domain": domain or norm_domain,
            "domain_status": "untested",
            "mx_status": "untested",
            "mx_records": [],
            "is_null_mx": False,
            "primary_mx": None,
            "is_disposable": False,
            "recipient_status": "untested",
            "provider_info": None,
            "smtp_status": "skipped",
            "classification": classification,
            "status_category": status_cat,
            "reason": reason,
            "duration_ms": duration_ms,
            "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

    # Stage 3: Disposable Domain Detection
    disposable = is_disposable_domain(domain)

    # Stage 4 & 5: Domain DNS check (with memoization)
    if domain_cache is not None and domain in domain_cache:
        dns_result = domain_cache[domain]
    else:
        dns_result = check_domain_dns(domain, resolver=resolver)
        if domain_cache is not None:
            domain_cache[domain] = dns_result

    domain_status = dns_result["domain_status"]
    mx_status = dns_result["mx_status"]
    mx_records = dns_result["mx_records"]
    primary_mx = dns_result.get("primary_mx")
    dns_err = dns_result.get("error")

    # If domain doesn't exist, has Null MX, or has DNS error, do not call provider
    provider_res = None
    smtp_info = None

    if domain_status == "exists" and mx_status in ("mx_found", "implicit_mx_found"):
        # Stage 6: Provider-based verification over HTTPS (port 443)
        active_provider = provider or get_verification_provider()
        provider_res = active_provider.verify_recipient(normalized_email)

        # Check if provider detected disposable
        if provider_res.get("is_disposable"):
            disposable = True

        # Optional legacy direct SMTP check (only if explicitly requested and enabled)
        enable_direct_smtp = os.environ.get("ENABLE_DIRECT_SMTP", "false").lower() == "true"
        if perform_smtp and enable_direct_smtp and primary_mx:
            smtp_info = check_smtp_recipient(normalized_email, primary_mx)

    # Stage 7: Result classification
    classification, status_cat, reason = classify_result(
        syntax_valid=True,
        domain_status=domain_status,
        mx_status=mx_status,
        is_disposable=disposable,
        provider_res=provider_res,
        smtp_info=smtp_info,
        domain_error=dns_err
    )

    recipient_status = "untested"
    if provider_res:
        recipient_status = provider_res.get("status", "unknown")
    elif smtp_info:
        recipient_status = smtp_info.get("smtp_status", "unknown")

    duration_ms = round((time.perf_counter() - start_t) * 1000, 1)

    return {
        "email": raw_email,
        "normalized_email": normalized_email,
        "syntax_valid": True,
        "domain": domain,
        "domain_status": domain_status,
        "mx_status": mx_status,
        "mx_records": mx_records,
        "is_null_mx": dns_result.get("is_null_mx", False),
        "primary_mx": primary_mx,
        "is_disposable": disposable,
        "recipient_status": recipient_status,
        "provider_info": {
            "provider": provider_res.get("provider") if provider_res else "none",
            "status": provider_res.get("status") if provider_res else "untested",
            "score": provider_res.get("score") if provider_res else None,
            "reason": provider_res.get("reason") if provider_res else None
        } if provider_res else None,
        "smtp_status": smtp_info.get("smtp_status", "skipped") if smtp_info else recipient_status,
        "classification": classification,
        "status_category": status_cat,
        "reason": reason,
        "duration_ms": duration_ms,
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }


def verify_email_list(
    emails: List[str],
    perform_smtp: bool = False,
    provider: Optional[BaseVerificationProvider] = None,
    max_emails: int = 100
) -> Dict[str, Any]:
    """
    Verifies a batch of email addresses up to max_emails (default 100).
    - Caches domain and email lookups.
    - Preserves input order in results.
    - Computes summary counts for Valid, Invalid, Risky, and Unknown.
    """
    if not isinstance(emails, list):
        raise ValueError("Input 'emails' must be a list of strings.")

    if len(emails) == 0:
        raise ValueError("Email list is empty.")

    if len(emails) > max_emails:
        raise ValueError(f"Too many addresses. Maximum allowed per request is {max_emails}.")

    resolver = get_configured_resolver(timeout=3.5)
    active_provider = provider or get_verification_provider()
    domain_cache: Dict[str, Dict[str, Any]] = {}
    email_cache: Dict[str, Dict[str, Any]] = {}

    results = []
    summary = {
        "total": len(emails),
        "valid": 0,
        "invalid": 0,
        "risky": 0,
        "unknown": 0,
        # Backward-compatible aliases for existing frontends/consumers:
        "likely_to_deliver": 0,
        "likely_to_bounce": 0
    }

    for item in emails:
        raw_email = str(item).strip() if item is not None else ""
        cache_key = raw_email.lower()

        if cache_key in email_cache:
            cached_res = dict(email_cache[cache_key])
            cached_res["email"] = raw_email  # Preserve input casing
            res = cached_res
        else:
            res = verify_single_email(
                raw_email,
                resolver=resolver,
                provider=active_provider,
                perform_smtp=perform_smtp,
                domain_cache=domain_cache
            )
            email_cache[cache_key] = res

        results.append(res)

        cat = res.get("status_category", "unknown").lower()
        if cat == "valid":
            summary["valid"] += 1
            summary["likely_to_deliver"] += 1
        elif cat == "invalid":
            summary["invalid"] += 1
            summary["likely_to_bounce"] += 1
        elif cat == "risky":
            summary["risky"] += 1
        else:
            summary["unknown"] += 1

    return {
        "success": True,
        "total": len(results),
        "provider": active_provider.name,
        "summary": summary,
        "results": results
    }


def check_domain_diagnostics(
    domain_input: str,
    resolver: Optional[dns.resolver.Resolver] = None
) -> Dict[str, Any]:
    """
    Dedicated diagnostic tool for domain-level mail routing inspection.
    Evaluates:
    - Domain syntax and sanitization
    - DNS resolution status (exists, nonexistent, timeout, error)
    - MX records and preferences
    - RFC 7505 Null MX detection
    - RFC 5321 Implicit MX (A/AAAA records)
    - Disposable domain detection
    - Evidence whether the domain is configured to receive email
    """
    start_t = time.perf_counter()
    clean = str(domain_input or "").strip().lower()
    # Strip protocol prefixes or URL paths if pasted accidentally
    clean = re.sub(r"^https?://", "", clean)
    clean = clean.split("/")[0].split(":")[0].strip().rstrip(".")

    if not clean:
        return {
            "success": False,
            "domain": "",
            "syntax_valid": False,
            "error": "Domain name cannot be empty."
        }

    # Domain syntax check (RFC 1035 / RFC 1123)
    domain_regex = re.compile(
        r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}$"
    )
    if not domain_regex.match(clean):
        return {
            "success": False,
            "domain": clean,
            "syntax_valid": False,
            "error": f"Invalid domain syntax: '{clean}' is not a valid fully qualified domain name."
        }

    disposable = is_disposable_domain(clean)
    dns_res = check_domain_dns(clean, resolver=resolver)

    domain_status = dns_res.get("domain_status", "unknown")
    mx_status = dns_res.get("mx_status", "unknown")
    is_null_mx = dns_res.get("is_null_mx", False)
    mx_records = dns_res.get("mx_records", [])
    primary_mx = dns_res.get("primary_mx")
    dns_error = dns_res.get("error")

    can_receive_email = False
    verdict = "Inconclusive"
    confidence = "Low"
    routing_explanation = ""

    if domain_status == "nonexistent":
        verdict = "Domain Nonexistent"
        confidence = "High"
        routing_explanation = "The domain does not exist in DNS (NXDOMAIN). Mail sent to this domain will bounce."
    elif is_null_mx or mx_status == "null_mx":
        verdict = "Rejects All Email (Null MX)"
        confidence = "High"
        routing_explanation = "Domain publishes an RFC 7505 Null MX record ('0 .'), explicitly declaring that it does not accept email under any circumstances."
    elif mx_status == "no_records":
        verdict = "No Mail Routing Configured"
        confidence = "High"
        routing_explanation = "The domain exists in DNS, but lacks MX, A, or AAAA mail routing records. Email cannot be delivered."
    elif mx_status in ("dns_timeout", "dns_error") or domain_status in ("dns_timeout", "dns_error"):
        verdict = "DNS Resolution Failed"
        confidence = "Inconclusive"
        routing_explanation = f"DNS query could not be completed: {dns_error or 'Nameserver timeout'}."
    elif mx_status in ("mx_found", "implicit_mx_found"):
        can_receive_email = True
        confidence = "High" if mx_status == "mx_found" else "Moderate"
        routing_type = "Active MX records found" if mx_status == "mx_found" else "RFC 5321 Implicit MX (A/AAAA fallback)"
        verdict = f"Ready to Receive Mail ({routing_type})"
        routing_explanation = (
            f"Domain mail routing is active ({len(mx_records)} record{'s' if len(mx_records) != 1 else ''}). "
            "Note: Domain mail routing confirms the server is configured to accept mail, but does NOT prove that any individual recipient inbox exists."
        )
        if disposable:
            routing_explanation += " Warning: This domain is a known temporary or disposable email service."

    duration_ms = round((time.perf_counter() - start_t) * 1000, 1)

    return {
        "success": True,
        "domain": clean,
        "syntax_valid": True,
        "domain_status": domain_status,
        "mx_status": mx_status,
        "mx_records": mx_records,
        "primary_mx": primary_mx,
        "is_null_mx": is_null_mx,
        "is_disposable": disposable,
        "can_receive_email": can_receive_email,
        "verdict": verdict,
        "confidence": confidence,
        "routing_explanation": routing_explanation,
        "disclaimer": "Domain-level mail routing confirms that mail servers are configured to receive messages for this domain. It does not verify individual recipient inbox existence.",
        "duration_ms": duration_ms,
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }
