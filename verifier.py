"""
EmailCheck - Verification Core Logic
Provides syntax validation, DNS/MX record verification (with RFC 5321 implicit MX fallback),
and safe, non-invasive SMTP recipient checks.
"""

import re
import socket
import smtplib
from typing import Dict, Any, List, Optional, Tuple
import dns.resolver
import dns.exception

try:
    import email_validator
    from email_validator import validate_email as ext_validate_email, EmailNotValidError
    HAS_EMAIL_VALIDATOR = True
except ImportError:
    HAS_EMAIL_VALIDATOR = False


# Reliable fallback nameservers to avoid local/virtual adapter timeouts
PUBLIC_NAMESERVERS = ['8.8.8.8', '1.1.1.1', '8.8.4.4', '1.0.0.1']

# RFC 5322 compliant regex for fallback / secondary validation
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


def validate_syntax(email: str) -> Tuple[bool, str, str, Optional[str]]:
    """
    Validates email syntax against RFC standards.
    Returns:
        (is_valid: bool, local_part: str, domain: str, error_message: Optional[str])
    """
    if not email or not isinstance(email, str):
        return False, "", "", "Email address is empty or not a valid string."

    email = email.strip()
    if len(email) > 254:
        return False, "", "", "Email exceeds maximum RFC length of 254 characters."

    if "@" not in email:
        return False, "", "", "Missing '@' symbol in email address."

    parts = email.split("@")
    if len(parts) != 2:
        return False, "", "", "Email contains multiple '@' symbols."

    local_part, domain = parts[0], parts[1]

    if not local_part:
        return False, "", domain, "Missing local part before '@'."
    if len(local_part) > 64:
        return False, local_part, domain, "Local part exceeds 64 characters."
    if local_part.startswith(".") or local_part.endswith("."):
        return False, local_part, domain, "Local part cannot start or end with a dot."
    if ".." in local_part:
        return False, local_part, domain, "Local part cannot contain consecutive dots ('..')."

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

    # Validate with email-validator library if available
    if HAS_EMAIL_VALIDATOR:
        try:
            val = ext_validate_email(email, check_deliverability=False)
            normalized_domain = val.domain.lower()
            return True, val.local_part, normalized_domain, None
        except EmailNotValidError as err:
            return False, local_part, domain.lower(), str(err)
        except Exception as ex:
            return False, local_part, domain.lower(), f"Syntax validation failed: {str(ex)}"

    # Regex fallback
    if not EMAIL_REGEX.match(email):
        return False, local_part, domain.lower(), "Email format does not adhere to RFC 5322 syntax."

    return True, local_part, domain.lower(), None


def check_domain_dns(
    domain: str,
    resolver: Optional[dns.resolver.Resolver] = None,
    timeout: float = 3.5
) -> Dict[str, Any]:
    """
    Checks DNS records for the domain:
    1. Query MX records.
    2. Fallback to A/AAAA records (RFC 5321 Implicit MX) if no MX is found.
    Handles NXDOMAIN, timeouts, and missing records.
    """
    res = resolver or get_configured_resolver(timeout=timeout)
    domain_clean = domain.strip().rstrip(".")

    # Handle IDNA encoding for internationalized domains
    try:
        domain_ascii = domain_clean.encode("idna").decode("ascii")
    except Exception:
        domain_ascii = domain_clean

    result = {
        "domain": domain_clean,
        "domain_status": "unknown",  # "exists", "nonexistent", "dns_timeout", "dns_error"
        "mx_status": "unknown",      # "mx_found", "implicit_mx_found", "no_records", "none", "dns_error"
        "mx_records": [],            # List of records e.g. ["mail.example.com (pref: 10)"]
        "primary_mx": None,          # Hostname of highest priority MX
        "error": None
    }

    # Step 1: Query MX records
    try:
        mx_answers = res.resolve(domain_ascii, "MX")
        sorted_mx = sorted(mx_answers, key=lambda r: r.preference)
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
        # Domain does not exist
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
            # Check AAAA as well
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


def check_smtp_recipient(
    email: str,
    mx_host: str,
    sender: str = "verify@emailcheck.app",
    timeout: float = 3.5
) -> Dict[str, Any]:
    """
    Safely attempts an SMTP handshake with the primary mail server.
    CRITICAL SAFETY RULES:
    1. NEVER send an email.
    2. NEVER issue SMTP DATA or transmit message bodies.
    3. Handles timeouts, connection refused, greylisting, and catch-all detection.
    4. Quits immediately after recipient verification.
    """
    result = {
        "smtp_attempted": True,
        "smtp_status": "unknown",
        # statuses: "mailbox_accepted", "mailbox_rejected", "catch_all",
        #           "temporary_failure", "unverified", "connection_failed", "timeout", "skipped"
        "code": None,
        "is_catch_all": False,
        "reason": None
    }

    if not mx_host:
        result["smtp_attempted"] = False
        result["smtp_status"] = "skipped"
        result["reason"] = "No MX host available for SMTP verification."
        return result

    smtp_client = None
    try:
        # Establish connection with short timeout
        smtp_client = smtplib.SMTP(timeout=timeout)
        code, resp = smtp_client.connect(mx_host, 25)
        
        # Initial greeting check
        if code >= 400:
            result["smtp_status"] = "connection_failed"
            result["code"] = code
            result["reason"] = f"Mail server rejected connection with code {code}."
            return result

        # HELO / EHLO
        smtp_client.ehlo_or_helo_if_needed()

        # MAIL FROM
        code, resp = smtp_client.mail(sender)
        if code >= 400:
            result["smtp_status"] = "unverified"
            result["code"] = code
            result["reason"] = f"Server rejected MAIL FROM ({code}): {resp.decode('utf-8', 'ignore') if isinstance(resp, bytes) else resp}"
            return result

        # RCPT TO target email
        code, resp = smtp_client.rcpt(email)
        resp_str = resp.decode("utf-8", "ignore") if isinstance(resp, bytes) else str(resp)
        result["code"] = code

        if code == 250:
            # Address accepted. Now perform non-invasive catch-all test
            # using a random nonexistent mailbox name on the same domain
            domain = email.split("@")[-1]
            probe_user = "nonexistent_probe_check_7921x"
            probe_email = f"{probe_user}@{domain}"
            
            try:
                probe_code, probe_resp = smtp_client.rcpt(probe_email)
                if probe_code == 250:
                    # Server accepts ANY recipient -> Catch-all domain
                    result["smtp_status"] = "catch_all"
                    result["is_catch_all"] = True
                    result["reason"] = "Domain mail server is configured as catch-all (accepts non-existent addresses)."
                    return result
            except Exception:
                pass  # If catch-all probe fails, continue with 250 result

            result["smtp_status"] = "mailbox_accepted"
            result["reason"] = "Mail server accepted recipient in SMTP handshake (250 OK)."
            return result

        elif code in (550, 551, 552, 553, 554):
            result["smtp_status"] = "mailbox_rejected"
            result["reason"] = f"Mail server explicitly rejected address ({code}): {resp_str.strip()}"
            return result

        elif code in (421, 450, 451, 452):
            result["smtp_status"] = "temporary_failure"
            result["reason"] = f"Temporary mail server response / greylisting ({code}): {resp_str.strip()}"
            return result

        elif code == 252:
            result["smtp_status"] = "unverified"
            result["reason"] = "Mail server refuses to verify mailbox existence (SMTP 252)."
            return result

        else:
            result["smtp_status"] = "ambiguous"
            result["reason"] = f"Mail server returned ambiguous status ({code}): {resp_str.strip()}"
            return result

    except (socket.timeout, TimeoutError):
        result["smtp_status"] = "timeout"
        result["reason"] = "SMTP connection timed out (server unreachable or port 25 restricted)."
        return result

    except (ConnectionRefusedError, socket.error, OSError) as err:
        result["smtp_status"] = "connection_failed"
        result["reason"] = f"SMTP connection failed (port 25 blocked by provider or host unreachable): {str(err)}"
        return result

    except smtplib.SMTPException as err:
        result["smtp_status"] = "smtp_error"
        result["reason"] = f"SMTP protocol error: {str(err)}"
        return result

    except Exception as err:
        result["smtp_status"] = "unknown"
        result["reason"] = f"Unexpected SMTP error: {str(err)}"
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


def classify_result(
    syntax_valid: bool,
    domain_status: str,
    mx_status: str,
    smtp_info: Optional[Dict[str, Any]],
    syntax_error: Optional[str] = None,
    domain_error: Optional[str] = None
) -> Tuple[str, str]:
    """
    Determines the final classification and human-readable explanation:
    - Likely to be Delivered
    - Likely to Bounce
    - Unknown
    """
    # 1. Syntax Check
    if not syntax_valid:
        msg = f"Invalid email syntax: {syntax_error or 'malformed structure'}."
        return "Likely to Bounce", msg

    # 2. Domain / DNS Checks
    if domain_status == "nonexistent":
        return "Likely to Bounce", "The domain does not exist in DNS (NXDOMAIN). Mail sent to this address will bounce."

    if mx_status == "no_records":
        return "Likely to Bounce", "Domain exists, but has no MX or A records configured to receive email."

    if domain_status in ("dns_timeout", "dns_error") or mx_status in ("dns_timeout", "dns_error"):
        return "Unknown", f"DNS query could not be completed ({domain_error or 'timeout/server failure'})."

    # 3. SMTP Verification Checks (if attempted)
    if smtp_info and smtp_info.get("smtp_attempted"):
        smtp_status = smtp_info.get("smtp_status")
        smtp_reason = smtp_info.get("reason", "")
        is_catch_all = smtp_info.get("is_catch_all", False)

        if smtp_status == "mailbox_rejected":
            return "Likely to Bounce", f"Mail server explicitly rejected mailbox: {smtp_reason}."

        if smtp_status == "catch_all" or is_catch_all:
            return "Unknown", "Domain server is configured as catch-all (accepts any mailbox). Individual mailbox existence cannot be confirmed."

        if smtp_status in ("connection_failed", "timeout"):
            return "Unknown", "Outbound SMTP connection was blocked or timed out (standard mail port 25 restricted on hosting platform). Mail routing is valid, but specific mailbox existence cannot be confirmed."

        if smtp_status in ("temporary_failure", "unverified", "ambiguous", "smtp_error"):
            return "Unknown", f"SMTP verification inconclusive ({smtp_reason})."

        if smtp_status == "mailbox_accepted":
            return "Likely to be Delivered", "Syntax is valid, MX routing is active, and mail server accepted recipient in SMTP handshake. Note: Inbox delivery depends on spam filters and recipient policies."

    # 4. Standard DNS Mode (Valid syntax + verified MX routing, non-invasive)
    if mx_status in ("mx_found", "implicit_mx_found"):
        routing_desc = "active MX mail routing" if mx_status == "mx_found" else "implicit MX (A/AAAA) fallback routing"
        return "Likely to be Delivered", (
            f"Valid syntax and {routing_desc} verified. "
            "Note: This confirms the domain is prepared to receive mail, but is not an absolute guarantee of inbox delivery."
        )

    return "Unknown", "Unable to establish verification status based on available non-invasive checks."


def verify_single_email(
    email_str: str,
    resolver: Optional[dns.resolver.Resolver] = None,
    perform_smtp: bool = False,
    domain_cache: Optional[Dict[str, Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Performs complete verification pipeline for a single email address.
    Utilizes domain_cache to prevent duplicate DNS/MX resolutions.
    """
    raw_email = str(email_str).strip()
    
    # Syntax validation
    syntax_valid, local_part, domain, syntax_err = validate_syntax(raw_email)

    if not syntax_valid:
        classification, reason = classify_result(
            syntax_valid=False,
            domain_status="untested",
            mx_status="untested",
            smtp_info=None,
            syntax_error=syntax_err
        )
        return {
            "email": raw_email,
            "syntax_valid": False,
            "domain": domain,
            "domain_status": "untested",
            "mx_status": "untested",
            "mx_records": [],
            "smtp_status": "skipped",
            "smtp_details": None,
            "classification": classification,
            "reason": reason
        }

    # Domain DNS check (with memoization)
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

    # If domain doesn't exist or has DNS errors, don't attempt SMTP
    smtp_info = None
    if perform_smtp and mx_status in ("mx_found", "implicit_mx_found") and primary_mx:
        smtp_info = check_smtp_recipient(raw_email, primary_mx)
    else:
        smtp_info = {
            "smtp_attempted": False,
            "smtp_status": "skipped",
            "reason": "SMTP verification not requested or mail host unavailable."
        }

    classification, reason = classify_result(
        syntax_valid=True,
        domain_status=domain_status,
        mx_status=mx_status,
        smtp_info=smtp_info,
        domain_error=dns_err
    )

    return {
        "email": raw_email,
        "syntax_valid": True,
        "domain": domain,
        "domain_status": domain_status,
        "mx_status": mx_status,
        "mx_records": mx_records,
        "smtp_status": smtp_info.get("smtp_status", "skipped"),
        "smtp_details": {
            "code": smtp_info.get("code"),
            "is_catch_all": smtp_info.get("is_catch_all", False),
            "reason": smtp_info.get("reason")
        } if smtp_info.get("smtp_attempted") else None,
        "classification": classification,
        "reason": reason
    }


def verify_email_list(
    emails: List[str],
    perform_smtp: bool = False,
    max_emails: int = 100
) -> Dict[str, Any]:
    """
    Verifies a list of email addresses.
    - Limits size to max_emails (default 100).
    - Caches domain and email lookups to optimize performance and prevent repeated DNS/SMTP queries.
    - Preserves input order in results.
    - Produces aggregate summary counts.
    """
    if not isinstance(emails, list):
        raise ValueError("Input 'emails' must be a list of strings.")

    if len(emails) == 0:
        raise ValueError("Email list is empty.")

    if len(emails) > max_emails:
        raise ValueError(f"Too many addresses. Maximum allowed per request is {max_emails}.")

    resolver = get_configured_resolver(timeout=3.5)
    domain_cache: Dict[str, Dict[str, Any]] = {}
    email_cache: Dict[str, Dict[str, Any]] = {}

    results = []
    summary = {
        "total": len(emails),
        "likely_to_deliver": 0,
        "likely_to_bounce": 0,
        "unknown": 0
    }

    for item in emails:
        raw_email = str(item).strip() if item is not None else ""
        cache_key = (raw_email.lower(), perform_smtp)

        if cache_key in email_cache:
            # Duplicate address within request: reuse cached verification
            cached_res = dict(email_cache[cache_key])
            cached_res["email"] = raw_email  # Preserve original casing
            res = cached_res
        else:
            res = verify_single_email(
                raw_email,
                resolver=resolver,
                perform_smtp=perform_smtp,
                domain_cache=domain_cache
            )
            email_cache[cache_key] = res

        results.append(res)

        # Count summary
        classification = res["classification"]
        if classification == "Likely to be Delivered":
            summary["likely_to_deliver"] += 1
        elif classification == "Likely to Bounce":
            summary["likely_to_bounce"] += 1
        else:
            summary["unknown"] += 1

    return {
        "success": True,
        "total": len(results),
        "summary": summary,
        "results": results
    }
