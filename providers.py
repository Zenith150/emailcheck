"""
EmailCheck - Email Verification Providers Module
Implements HTTPS (port 443) recipient verification providers, disposable domain detection,
and local fallback engines without requiring outbound SMTP port 25 connections.
"""

import os
import json
import logging
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, Any, Optional

logger = logging.getLogger("EmailCheck.Providers")

# Curated dataset of known disposable / temporary email domains
DISPOSABLE_DOMAINS = {
    "10minutemail.com", "10minutemail.net", "10minutemail.org", "10mail.org",
    "20minutemail.com", "20mail.it", "guerrillamail.com", "guerrillamail.net",
    "guerrillamail.org", "guerrillamail.biz", "guerrillamailblock.com", "sharklasers.com",
    "grr.la", "pokemail.net", "spam4.me", "mailinator.com", "mailinator.net",
    "mailinator2.com", "suremail.info", "superstachel.de", "binkmail.com",
    "safetymail.info", "tradermail.info", "veryrealemail.com", "zippymail.info",
    "trashmail.com", "trashmail.net", "trashmail.me", "trash-mail.at",
    "yopmail.com", "yopmail.fr", "yopmail.net", "cool.fr.nf", "jetable.fr.nf",
    "courriel.fr.nf", "moncourrier.fr.nf", "monemail.fr.nf", "monmail.fr.nf",
    "tempmail.com", "temp-mail.org", "temp-mail.io", "tempail.com", "tempmailaddress.com",
    "dispostable.com", "throwawaymail.com", "fakemailgenerator.com", "fakeinbox.com",
    "emailondeck.com", "getairmail.com", "airmail.news", "mohmal.com", "mohmal.in",
    "inboxkitten.com", "burnermail.io", "crazymailing.com", "mytemp.email",
    "maildrop.cc", "mailnesia.com", "nada.ltd", "nada.email", "getnada.com",
    "armyspy.com", "cuvox.de", "dayrep.com", "fleckens.hu", "gustr.com",
    "jourrapide.com", "rhyta.com", "superrito.com", "teleworm.us", "einrot.com",
    "generator.email", "zillamail.com", "disposablemail.com", "trashymail.com",
    "meltmail.com", "spambox.us", "mytempmail.com", "mintemail.com", "mailcatch.com",
    "inboxclean.com", "bouncr.com", "fakebox.org", "trashinbox.com", "tempinbox.com"
}


def is_disposable_domain(domain: str) -> bool:
    """Checks whether the given domain is a known disposable/temporary email provider."""
    if not domain:
        return False
    d = domain.strip().lower().rstrip(".")
    return d in DISPOSABLE_DOMAINS


class BaseVerificationProvider:
    """Base class for HTTPS email verification providers."""
    name: str = "base"

    def verify_recipient(self, email: str) -> Dict[str, Any]:
        """
        Verify recipient deliverability over HTTPS.
        Returns dict with:
            - status: "deliverable", "undeliverable", "risky", "unknown", "unavailable"
            - is_deliverable: bool or None
            - is_disposable: bool or None
            - is_catch_all: bool or None
            - is_role: bool or None
            - score: float (0.0 to 1.0) or None
            - provider: str
            - raw_status: str
            - reason: str
            - error: str or None
        """
        raise NotImplementedError


class LocalFallbackProvider(BaseVerificationProvider):
    """
    Fallback provider when no external API key is configured.
    Performs local disposable checks without claiming to verify recipient inbox existence.
    """
    name: str = "local"

    def verify_recipient(self, email: str) -> Dict[str, Any]:
        domain = email.split("@")[-1].lower() if "@" in email else ""
        disposable = is_disposable_domain(domain)
        if disposable:
            return {
                "status": "risky",
                "is_deliverable": None,
                "is_disposable": True,
                "is_catch_all": None,
                "is_role": None,
                "score": None,
                "provider": "local",
                "raw_status": "disposable",
                "reason": "Domain belongs to a known temporary/disposable email service.",
                "error": None
            }

        return {
            "status": "unavailable",
            "is_deliverable": None,
            "is_disposable": False,
            "is_catch_all": None,
            "is_role": None,
            "score": None,
            "provider": "local",
            "raw_status": "unverified",
            "reason": "Recipient verification provider API key not configured. Domain routing verified, but recipient inbox remains unverified.",
            "error": None
        }


class AbstractAPIProvider(BaseVerificationProvider):
    """
    Abstract API Email Validation integration over HTTPS (port 443).
    API Docs: https://www.abstractapi.com/api/email-verification-validation-api
    """
    name: str = "abstract"
    ENDPOINT = "https://emailvalidation.abstractapi.com/v1/"

    def __init__(self, api_key: str, timeout: float = 6.0):
        self.api_key = api_key.strip()
        self.timeout = timeout

    def verify_recipient(self, email: str) -> Dict[str, Any]:
        if not self.api_key:
            return LocalFallbackProvider().verify_recipient(email)

        params = urllib.parse.urlencode({
            "api_key": self.api_key,
            "email": email
        })
        url = f"{self.ENDPOINT}?{params}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "EmailCheck-Verifier/2.0",
                "Accept": "application/json"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                if response.status != 200:
                    return {
                        "status": "unknown",
                        "is_deliverable": None,
                        "is_disposable": None,
                        "is_catch_all": None,
                        "is_role": None,
                        "score": None,
                        "provider": self.name,
                        "raw_status": f"HTTP_{response.status}",
                        "reason": f"Provider API returned HTTP {response.status}.",
                        "error": f"HTTP_{response.status}"
                    }

                data = json.loads(response.read().decode("utf-8"))

                deliverability = data.get("deliverability", "").upper()
                is_disposable = data.get("is_disposable_email", {}).get("value")
                is_catchall = data.get("is_catchall_email", {}).get("value")
                is_role = data.get("is_role_email", {}).get("value")
                score = data.get("quality_score")
                is_smtp_valid = data.get("is_smtp_valid", {}).get("value")

                if deliverability == "DELIVERABLE" or is_smtp_valid is True:
                    status = "deliverable"
                    reason = "Recipient inbox verified deliverable by Abstract API."
                elif deliverability == "UNDELIVERABLE" or is_smtp_valid is False:
                    status = "undeliverable"
                    reason = "Recipient inbox confirmed undeliverable by Abstract API."
                elif deliverability == "RISKY" or is_catchall or is_disposable:
                    status = "risky"
                    reason = "Address flagged as risky (catch-all or disposable domain)."
                else:
                    status = "unknown"
                    reason = "Abstract API returned inconclusive deliverability status."

                return {
                    "status": status,
                    "is_deliverable": True if status == "deliverable" else (False if status == "undeliverable" else None),
                    "is_disposable": bool(is_disposable),
                    "is_catch_all": bool(is_catchall),
                    "is_role": bool(is_role),
                    "score": float(score) if score is not None else None,
                    "provider": self.name,
                    "raw_status": deliverability,
                    "reason": reason,
                    "error": None
                }

        except urllib.error.HTTPError as err:
            logger.warning("Abstract API HTTP error: code=%d", err.code)
            if err.code in (401, 403):
                reason = "Abstract API key is invalid or unauthorized."
            elif err.code in (422, 429):
                reason = "Abstract API quota exceeded or rate limit reached."
            else:
                reason = f"Abstract API error: HTTP {err.code}."
            return {
                "status": "unknown",
                "is_deliverable": None,
                "is_disposable": None,
                "is_catch_all": None,
                "is_role": None,
                "score": None,
                "provider": self.name,
                "raw_status": f"HTTP_{err.code}",
                "reason": reason,
                "error": str(err)
            }

        except (urllib.error.URLError, TimeoutError) as err:
            logger.warning("Abstract API network error / timeout: %s", str(err))
            return {
                "status": "unknown",
                "is_deliverable": None,
                "is_disposable": None,
                "is_catch_all": None,
                "is_role": None,
                "score": None,
                "provider": self.name,
                "raw_status": "timeout",
                "reason": "Abstract API request timed out or network was unreachable.",
                "error": str(err)
            }
        except Exception as exc:
            logger.error("Abstract API unexpected error: %s", str(exc))
            return {
                "status": "unknown",
                "is_deliverable": None,
                "is_disposable": None,
                "is_catch_all": None,
                "is_role": None,
                "score": None,
                "provider": self.name,
                "raw_status": "error",
                "reason": f"Unexpected error communicating with verification provider: {str(exc)}",
                "error": str(exc)
            }


class HunterProvider(BaseVerificationProvider):
    """
    Hunter.io Email Verifier API over HTTPS (port 443).
    API Docs: https://hunter.io/api/email-verifier
    """
    name: str = "hunter"
    ENDPOINT = "https://api.hunter.io/v2/email-verifier"

    def __init__(self, api_key: str, timeout: float = 6.0):
        self.api_key = api_key.strip()
        self.timeout = timeout

    def verify_recipient(self, email: str) -> Dict[str, Any]:
        if not self.api_key:
            return LocalFallbackProvider().verify_recipient(email)

        params = urllib.parse.urlencode({
            "api_key": self.api_key,
            "email": email
        })
        url = f"{self.ENDPOINT}?{params}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "EmailCheck-Verifier/2.0",
                "Accept": "application/json"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                if response.status != 200:
                    return {
                        "status": "unknown",
                        "is_deliverable": None,
                        "is_disposable": None,
                        "is_catch_all": None,
                        "is_role": None,
                        "score": None,
                        "provider": self.name,
                        "raw_status": f"HTTP_{response.status}",
                        "reason": f"Hunter API returned HTTP {response.status}.",
                        "error": f"HTTP_{response.status}"
                    }

                res_json = json.loads(response.read().decode("utf-8"))
                data = res_json.get("data", {})

                result_field = data.get("result", "").lower()
                status_field = data.get("status", "").lower()
                score = data.get("score")
                is_disposable = data.get("disposable")
                is_catchall = data.get("accept_all")

                if result_field == "deliverable" or status_field == "valid":
                    status = "deliverable"
                    reason = "Recipient inbox verified deliverable by Hunter.io."
                elif result_field == "undeliverable" or status_field == "invalid":
                    status = "undeliverable"
                    reason = "Recipient inbox verified undeliverable by Hunter.io."
                elif result_field == "risky" or is_catchall or is_disposable:
                    status = "risky"
                    reason = "Hunter.io classified address as risky (accept-all server or disposable domain)."
                else:
                    status = "unknown"
                    reason = "Hunter.io returned inconclusive deliverability status."

                return {
                    "status": status,
                    "is_deliverable": True if status == "deliverable" else (False if status == "undeliverable" else None),
                    "is_disposable": bool(is_disposable),
                    "is_catch_all": bool(is_catchall),
                    "is_role": None,
                    "score": (float(score) / 100.0) if score is not None else None,
                    "provider": self.name,
                    "raw_status": f"{result_field}/{status_field}",
                    "reason": reason,
                    "error": None
                }

        except urllib.error.HTTPError as err:
            logger.warning("Hunter API HTTP error: code=%d", err.code)
            if err.code in (401, 403):
                reason = "Hunter.io API key is invalid or unauthorized."
            elif err.code in (422, 429):
                reason = "Hunter.io API quota exceeded or rate limit reached."
            else:
                reason = f"Hunter.io API error: HTTP {err.code}."
            return {
                "status": "unknown",
                "is_deliverable": None,
                "is_disposable": None,
                "is_catch_all": None,
                "is_role": None,
                "score": None,
                "provider": self.name,
                "raw_status": f"HTTP_{err.code}",
                "reason": reason,
                "error": str(err)
            }

        except (urllib.error.URLError, TimeoutError) as err:
            logger.warning("Hunter API network error / timeout: %s", str(err))
            return {
                "status": "unknown",
                "is_deliverable": None,
                "is_disposable": None,
                "is_catch_all": None,
                "is_role": None,
                "score": None,
                "provider": self.name,
                "raw_status": "timeout",
                "reason": "Hunter.io request timed out or network was unreachable.",
                "error": str(err)
            }
        except Exception as exc:
            return {
                "status": "unknown",
                "is_deliverable": None,
                "is_disposable": None,
                "is_catch_all": None,
                "is_role": None,
                "score": None,
                "provider": self.name,
                "raw_status": "error",
                "reason": f"Unexpected Hunter.io error: {str(exc)}",
                "error": str(exc)
            }


class ZeroBounceProvider(BaseVerificationProvider):
    """
    ZeroBounce Email Validation API over HTTPS (port 443).
    API Docs: https://www.zerobounce.net/docs/email-validation-api-quickstart/
    """
    name: str = "zerobounce"
    ENDPOINT = "https://api.zerobounce.net/v2/validate"

    def __init__(self, api_key: str, timeout: float = 6.0):
        self.api_key = api_key.strip()
        self.timeout = timeout

    def verify_recipient(self, email: str) -> Dict[str, Any]:
        if not self.api_key:
            return LocalFallbackProvider().verify_recipient(email)

        params = urllib.parse.urlencode({
            "api_key": self.api_key,
            "email": email,
            "ip_address": ""
        })
        url = f"{self.ENDPOINT}?{params}"

        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "EmailCheck-Verifier/2.0",
                "Accept": "application/json"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                if response.status != 200:
                    return {
                        "status": "unknown",
                        "is_deliverable": None,
                        "is_disposable": None,
                        "is_catch_all": None,
                        "is_role": None,
                        "score": None,
                        "provider": self.name,
                        "raw_status": f"HTTP_{response.status}",
                        "reason": f"ZeroBounce API returned HTTP {response.status}.",
                        "error": f"HTTP_{response.status}"
                    }

                data = json.loads(response.read().decode("utf-8"))
                zb_status = str(data.get("status", "")).lower()
                sub_status = str(data.get("sub_status", "")).lower()

                if zb_status == "valid":
                    status = "deliverable"
                    reason = "Recipient inbox verified deliverable by ZeroBounce."
                elif zb_status == "invalid":
                    status = "undeliverable"
                    reason = f"ZeroBounce confirmed mailbox invalid ({sub_status or 'undeliverable'})."
                elif zb_status in ("catch-all", "spamtrap", "abuse", "do_not_mail"):
                    status = "risky"
                    reason = f"ZeroBounce classified mailbox as risky ({zb_status})."
                else:
                    status = "unknown"
                    reason = "ZeroBounce returned inconclusive deliverability status."

                return {
                    "status": status,
                    "is_deliverable": True if status == "deliverable" else (False if status == "undeliverable" else None),
                    "is_disposable": (sub_status == "disposable"),
                    "is_catch_all": (zb_status == "catch-all"),
                    "is_role": (sub_status == "role_based"),
                    "score": None,
                    "provider": self.name,
                    "raw_status": zb_status,
                    "reason": reason,
                    "error": None
                }

        except urllib.error.HTTPError as err:
            logger.warning("ZeroBounce API HTTP error: code=%d", err.code)
            if err.code in (401, 403):
                reason = "ZeroBounce API key is invalid or unauthorized."
            elif err.code in (422, 429):
                reason = "ZeroBounce API quota exceeded or rate limit reached."
            else:
                reason = f"ZeroBounce API error: HTTP {err.code}."
            return {
                "status": "unknown",
                "is_deliverable": None,
                "is_disposable": None,
                "is_catch_all": None,
                "is_role": None,
                "score": None,
                "provider": self.name,
                "raw_status": f"HTTP_{err.code}",
                "reason": reason,
                "error": str(err)
            }
        except (urllib.error.URLError, TimeoutError) as err:
            return {
                "status": "unknown",
                "is_deliverable": None,
                "is_disposable": None,
                "is_catch_all": None,
                "is_role": None,
                "score": None,
                "provider": self.name,
                "raw_status": "timeout",
                "reason": "ZeroBounce request timed out or network was unreachable.",
                "error": str(err)
            }
        except Exception as exc:
            return {
                "status": "unknown",
                "is_deliverable": None,
                "is_disposable": None,
                "is_catch_all": None,
                "is_role": None,
                "score": None,
                "provider": self.name,
                "raw_status": "error",
                "reason": f"Unexpected ZeroBounce error: {str(exc)}",
                "error": str(exc)
            }


def get_verification_provider(
    provider_name: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = 6.0
) -> BaseVerificationProvider:
    """
    Factory function returning the configured HTTPS verification provider.
    Inspects environment variables if not passed explicitly:
      - EMAIL_VERIFICATION_PROVIDER (default: 'abstract')
      - EMAIL_VERIFICATION_API_KEY
    Falls back to LocalFallbackProvider when API key is missing.
    """
    p_name = (provider_name or os.environ.get("EMAIL_VERIFICATION_PROVIDER", "abstract")).strip().lower()
    key = (api_key or os.environ.get("EMAIL_VERIFICATION_API_KEY", "")).strip()

    if not key or p_name in ("none", "local", "disabled"):
        return LocalFallbackProvider()

    if p_name == "abstract":
        return AbstractAPIProvider(api_key=key, timeout=timeout)
    elif p_name == "hunter":
        return HunterProvider(api_key=key, timeout=timeout)
    elif p_name == "zerobounce":
        return ZeroBounceProvider(api_key=key, timeout=timeout)
    else:
        logger.warning("Unrecognized provider '%s', defaulting to LocalFallbackProvider", p_name)
        return LocalFallbackProvider()
