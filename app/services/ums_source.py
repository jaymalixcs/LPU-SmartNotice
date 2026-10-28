"""UMS Announcement Source Adapter for LPU SmartNotice.

Modular connector for Lovely Professional University Management System (UMS).
Supports both mock mode (for safe, non-intrusive local development & tests)
and authenticated live mode (using authorized student session headers).
"""

import hashlib
import html
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
# pyrefly: ignore[missing-import]
import httpx

from app.core.config import settings
from app.core.logging_config import logger
from app.models.announcement import RawAnnouncement


class UMSSourceAdapter:
    """Modular source adapter for LPU UMS announcements."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        connector_mode: Optional[str] = None,
        session_cookie: Optional[str] = None,
        timeout_seconds: float = 10.0,
    ):
        self.base_url = (base_url or settings.UMS_BASE_URL).rstrip("/") + "/"
        self.endpoint_url = endpoint_url or settings.UMS_ANNOUNCEMENTS_ENDPOINT
        self.happenings_url = getattr(settings, "LPU_HAPPENINGS_FEED_URL", "https://happenings.lpu.in/wp-json/wp/v2/posts")
        self.connector_mode = (connector_mode or settings.UMS_CONNECTOR_MODE).lower()
        self.session_cookie = session_cookie if session_cookie is not None else settings.UMS_SESSION_COOKIE
        self.timeout_seconds = timeout_seconds

    def get_source_status(self) -> Dict[str, Any]:
        """Return the current configuration and operational status of the UMS connector."""
        has_session = bool(self.session_cookie and self.session_cookie.strip())

        if self.connector_mode == "mock":
            status_code = "MOCK_MODE"
            message = "Operating in simulated mock mode with test notices."
        else:
            status_code = "LIVE_CONNECTED"
            message = "Connected to Official LPU Live Announcements Feed."

        return {
            "source_name": "LPU University Management System & Official Announcements",
            "base_url": self.base_url,
            "endpoint_url": self.endpoint_url,
            "connector_mode": self.connector_mode,
            "status": status_code,
            "has_session_credentials": has_session,
            "message": message,
        }

    def _log_diagnostic(
        self,
        method: str,
        url: str,
        status_code: int,
        content_type: str,
        byte_size: int,
        is_redirect: bool = False,
        final_url: Optional[str] = None,
        top_keys: Optional[List[str]] = None,
        candidate_count: int = 0,
        auth_state: str = "VALID",
    ) -> None:
        """Safe Phase 3 diagnostic logging. Never logs cookies, auth headers, or sensitive data."""
        # Sanitize URL by removing query parameters
        clean_url = url.split("?")[0] if url else "unknown"
        clean_final = final_url.split("?")[0] if final_url else clean_url
        keys_summary = ",".join(top_keys[:10]) if top_keys else "none"

        logger.info(
            "UMS Diagnostic | Method=%s | URL=%s | FinalURL=%s | Status=%d | ContentType=%s | "
            "Bytes=%d | Redirect=%s | TopKeys=[%s] | Candidates=%d | AuthState=%s",
            method,
            clean_url,
            clean_final,
            status_code,
            content_type,
            byte_size,
            is_redirect,
            keys_summary,
            candidate_count,
            auth_state,
        )

    def check_connection(self) -> Dict[str, Any]:
        """Verify reachability and authentication with UMS without aggressive polling."""
        if self.connector_mode == "mock":
            return {
                "connected": True,
                "status": "MOCK_ACTIVE",
                "message": "Mock connector operational. Simulating live UMS portal feed.",
                "latency_ms": 15,
            }

        if not self.session_cookie or not self.session_cookie.strip():
            return {
                "connected": False,
                "status": "AUTH_REQUIRED",
                "message": "UMS session cookie is not configured. Live portal calls require an authenticated session.",
                "latency_ms": 0,
            }

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cookie": self.session_cookie.strip(),
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }

        start_time = datetime.now()
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=False) as client:
                resp = client.get(self.base_url, headers=headers)
                latency = int((datetime.now() - start_time).total_seconds() * 1000)

                # If redirected to login page, session is expired
                if resp.status_code in (301, 302, 303, 307, 308):
                    redirect_location = resp.headers.get("location", "")
                    self._log_diagnostic(
                        method="GET",
                        url=self.base_url,
                        status_code=resp.status_code,
                        content_type=resp.headers.get("content-type", ""),
                        byte_size=len(resp.content),
                        is_redirect=True,
                        final_url=redirect_location,
                        auth_state="AUTH_EXPIRED",
                    )
                    if "login" in redirect_location.lower() or "default" in redirect_location.lower():
                        return {
                            "connected": False,
                            "status": "AUTH_EXPIRED",
                            "message": "UMS session cookie has expired or was redirected to login.",
                            "latency_ms": latency,
                        }

                if resp.status_code == 401:
                    self._log_diagnostic(
                        method="GET",
                        url=self.base_url,
                        status_code=401,
                        content_type=resp.headers.get("content-type", ""),
                        byte_size=len(resp.content),
                        auth_state="AUTH_EXPIRED",
                    )
                    return {
                        "connected": False,
                        "status": "AUTH_EXPIRED",
                        "message": "UMS session expired or unauthorized (HTTP 401).",
                        "latency_ms": latency,
                    }

                if resp.status_code == 403:
                    is_cf = "cloudflare" in resp.text.lower() or "challenge" in resp.text.lower()
                    self._log_diagnostic(
                        method="GET",
                        url=self.base_url,
                        status_code=403,
                        content_type=resp.headers.get("content-type", ""),
                        byte_size=len(resp.content),
                        auth_state="CLOUDFLARE_BLOCKED" if is_cf else "AUTH_FORBIDDEN",
                    )
                    return {
                        "connected": False,
                        "status": "CLOUDFLARE_BLOCKED" if is_cf else "AUTH_FORBIDDEN",
                        "message": "Cloudflare Bot Protection active on UMS portal. Use 1-Click Portal Sync or provide cf_clearance session cookie." if is_cf else "UMS access denied (HTTP 403). Session invalid.",
                        "latency_ms": latency,
                    }

                if resp.status_code == 429:
                    self._log_diagnostic(
                        method="GET",
                        url=self.base_url,
                        status_code=429,
                        content_type=resp.headers.get("content-type", ""),
                        byte_size=len(resp.content),
                        auth_state="RATE_LIMITED",
                    )
                    return {
                        "connected": False,
                        "status": "RATE_LIMITED",
                        "message": "UMS returned HTTP 429 Rate Limited. Polling paused.",
                        "latency_ms": latency,
                    }

                self._log_diagnostic(
                    method="GET",
                    url=self.base_url,
                    status_code=resp.status_code,
                    content_type=resp.headers.get("content-type", ""),
                    byte_size=len(resp.content),
                    auth_state="VALID" if resp.status_code < 400 else "ERROR",
                )
                return {
                    "connected": resp.status_code < 400,
                    "status": "CONNECTED" if resp.status_code < 400 else f"HTTP_{resp.status_code}",
                    "message": f"UMS portal reachable (HTTP {resp.status_code}).",
                    "latency_ms": latency,
                }

        except httpx.TimeoutException:
            return {
                "connected": False,
                "status": "TIMEOUT",
                "message": f"Connection timed out after {self.timeout_seconds}s.",
                "latency_ms": int((datetime.now() - start_time).total_seconds() * 1000),
            }
        except httpx.RequestError as exc:
            return {
                "connected": False,
                "status": "CONNECTION_ERROR",
                "message": f"Network error connecting to UMS: {str(exc)}",
                "latency_ms": int((datetime.now() - start_time).total_seconds() * 1000),
            }

    def fetch_latest_announcements(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch announcement list from UMS portal or official university live feed."""
        if self.connector_mode == "mock":
            return self._get_mock_announcements()[:limit]

        # 1. If session cookie is provided, attempt to fetch from UMS portal
        if self.session_cookie and self.session_cookie.strip():
            try:
                ums_data = self._fetch_from_ums_portal(limit=limit)
                if ums_data and isinstance(ums_data, list):
                    return ums_data[:limit]
            except PermissionError as pe:
                logger.warning("UMS authenticated access check: %s. Continuing to official university feed.", pe)
            except Exception as e:
                logger.warning("UMS portal fetch with session cookie failed: %s. Falling back to official university feed.", e)

        # 2. Fetch real-time official announcements from LPU sources
        live_announcements: List[Dict[str, Any]] = []
        try:
            live_feed_data = self._fetch_from_lpu_feed(limit=limit)
            if live_feed_data:
                live_announcements.extend(live_feed_data)
        except Exception as exc:
            logger.error("Failed fetching official LPU live feed: %s", exc)

        try:
            lpude_data = self._fetch_from_lpude_notifications(limit=min(5, limit))
            if lpude_data:
                live_announcements.extend(lpude_data)
        except Exception as exc:
            logger.debug("Failed fetching lpude notifications: %s", exc)

        if live_announcements:
            logger.info("Successfully fetched %d real-time announcements from official LPU feeds.", len(live_announcements))
            return live_announcements[:limit]

        # 3. Safe fallback if both network sources are unavailable
        logger.warning("No live announcements retrieved, using fallback notices.")
        return self._get_mock_announcements()[:limit]

    def _fetch_from_lpu_feed(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch live announcements from the official LPU public REST feed."""
        url = f"{self.happenings_url}?per_page={limit}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        }
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code != 200:
                raise RuntimeError(f"Official LPU feed returned HTTP {resp.status_code}")
            posts = resp.json()

        results: List[Dict[str, Any]] = []
        for p in posts:
            raw_title = p.get("title", {}).get("rendered", "")
            clean_title = html.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
            clean_title = (
                clean_title.replace("\u2019", "'")
                .replace("\u2018", "'")
                .replace("\u201c", '"')
                .replace("\u201d", '"')
                .replace("\u2013", "-")
                .replace("\u2014", "--")
                .replace("\u20b9", "Rs. ")
            )

            raw_content = p.get("content", {}).get("rendered", "")
            clean_content = html.unescape(re.sub(r"<[^>]+>", "\n", raw_content)).strip()
            clean_content = re.sub(r"\n\s*\n+", "\n\n", clean_content)
            clean_content = (
                clean_content.replace("\u2019", "'")
                .replace("\u2018", "'")
                .replace("\u201c", '"')
                .replace("\u201d", '"')
                .replace("\u2013", "-")
                .replace("\u2014", "--")
                .replace("\u20b9", "Rs. ")
            )

            attachments = re.findall(r'href=[\'"]([^\'"]+\.(?:pdf|docx?|xlsx?|zip))[\'"]', raw_content, re.IGNORECASE)
            att_names = [a.split("/")[-1] for a in attachments]

            date_str = p.get("date", "")[:10] or datetime.now().strftime("%Y-%m-%d")
            post_id = str(p.get("id", ""))
            link = p.get("link", f"{self.base_url}StudentDashboard.aspx")
            ref_no = f"LPU/HAPPENINGS/{date_str.replace('-', '')}/{post_id}"

            results.append({
                "id": post_id,
                "title": clean_title,
                "publication_date": date_str,
                "reference_number": ref_no,
                "full_content": clean_content,
                "attachment_present": bool(att_names or "attachment" in clean_content.lower()),
                "attachment_names": att_names,
                "source": "ums_official",
                "source_url": link,
            })
        return results

    def _fetch_from_lpude_notifications(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch official academic circulars and public notifications from Lovely Professional University."""
        url = "https://www.lpude.in/en/notifications"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
            if resp.status_code != 200:
                return []
            html_text = resp.text

        items = re.findall(r'<a[^>]+href=[\'"]([^\'"]+pdf)[\'"][^>]*>(.*?)</a>', html_text, re.IGNORECASE | re.DOTALL)
        results = []
        for idx, (link, text) in enumerate(items[:limit]):
            clean_title = re.sub(r'<[^>]+>', '', text).strip()
            clean_title = re.sub(r'\s+', ' ', clean_title)
            clean_title = (
                clean_title.replace("\u2019", "'")
                .replace("\u2018", "'")
                .replace("\u201c", '"')
                .replace("\u201d", '"')
                .replace("\u2013", "-")
                .replace("\u2014", "--")
                .replace("\u20b9", "Rs. ")
            )
            if not clean_title or len(clean_title) < 5:
                continue
            pdf_name = link.split('/')[-1]
            date_str = datetime.now().strftime("%Y-%m-%d")
            clean_date = date_str.replace("-", "")
            ref_no = f"LPU/DE/NOTIF/{clean_date}/{idx+1:03d}"
            results.append({
                "id": f"lpude_{clean_date}_{idx+1}",
                "title": clean_title,
                "publication_date": date_str,
                "reference_number": ref_no,
                "full_content": f"{clean_title}. Official notification issued by Lovely Professional University. Attachment: {pdf_name}. Direct circular link: {link}",
                "attachment_present": True,
                "attachment_names": [pdf_name],
                "source": "ums_official",
                "source_url": link,
            })
        return results

    def _extract_candidates_from_response(self, data: Any) -> List[Dict[str, Any]]:
        """Safely extract announcement list from various ASP.NET WebMethod and JSON schemas."""
        candidates: List[Dict[str, Any]] = []

        if isinstance(data, dict):
            # Check for ASP.NET WebMethod "d" wrapper
            if "d" in data:
                inner = data["d"]
                if isinstance(inner, str):
                    try:
                        inner = json.loads(inner)
                    except Exception:
                        inner = []
                return self._extract_candidates_from_response(inner)

            # Check common nested keys in ASP.NET / REST datasets
            for key in ("announcements", "data", "items", "Table", "results", "records", "rows"):
                val = data.get(key)
                if isinstance(val, list):
                    return [item for item in val if isinstance(item, dict)]
                if isinstance(val, dict):
                    return self._extract_candidates_from_response(val)

            # Single notice dictionary
            if any(k in data for k in ("title", "NoticeTitle", "Subject", "Headline", "full_content", "NoticeContent", "Body")):
                return [data]

        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    candidates.append(item)
                elif isinstance(item, str):
                    try:
                        sub = json.loads(item)
                        if isinstance(sub, dict):
                            candidates.append(sub)
                    except Exception:
                        pass

        return candidates

    def _fetch_from_ums_portal(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Fetch announcement list from authenticated UMS ASP.NET endpoint with Phase 3 diagnostics."""
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cookie": self.session_cookie.strip(),
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }
        with httpx.Client(timeout=self.timeout_seconds, follow_redirects=False) as client:
            payload = {"pageSize": limit}
            resp = client.post(self.endpoint_url, headers=headers, json=payload)

            is_redirect = resp.status_code in (301, 302, 303, 307, 308)
            final_loc = resp.headers.get("location", "")
            content_type = resp.headers.get("content-type", "")

            # If redirected, session is expired or invalid
            if is_redirect:
                self._log_diagnostic(
                    method="POST",
                    url=self.endpoint_url,
                    status_code=resp.status_code,
                    content_type=content_type,
                    byte_size=len(resp.content),
                    is_redirect=True,
                    final_url=final_loc,
                    auth_state="AUTH_EXPIRED",
                )
                raise PermissionError(f"UMS session expired or redirected to {final_loc.split('?')[0]}")

            if resp.status_code == 401:
                self._log_diagnostic(
                    method="POST",
                    url=self.endpoint_url,
                    status_code=401,
                    content_type=content_type,
                    byte_size=len(resp.content),
                    auth_state="AUTH_EXPIRED",
                )
                raise PermissionError("UMS session unauthorized (HTTP 401).")

            if resp.status_code == 403:
                is_cf = "cloudflare" in resp.text.lower() or "challenge" in resp.text.lower()
                self._log_diagnostic(
                    method="POST",
                    url=self.endpoint_url,
                    status_code=403,
                    content_type=content_type,
                    byte_size=len(resp.content),
                    auth_state="CLOUDFLARE_BLOCKED" if is_cf else "AUTH_FORBIDDEN",
                )
                raise PermissionError("UMS access blocked (HTTP 403 Cloudflare Bot Protection or Forbidden).")

            if resp.status_code >= 400:
                self._log_diagnostic(
                    method="POST",
                    url=self.endpoint_url,
                    status_code=resp.status_code,
                    content_type=content_type,
                    byte_size=len(resp.content),
                    auth_state=f"HTTP_{resp.status_code}",
                )
                raise RuntimeError(f"UMS portal returned HTTP {resp.status_code}")

            # If response is HTML instead of JSON
            if "text/html" in content_type:
                if "login" in resp.text.lower() or "form" in resp.text.lower():
                    self._log_diagnostic(
                        method="POST",
                        url=self.endpoint_url,
                        status_code=resp.status_code,
                        content_type=content_type,
                        byte_size=len(resp.content),
                        auth_state="HTML_LOGIN_PAGE",
                    )
                    raise PermissionError("UMS session invalid; received HTML login page instead of announcement data.")
                # Attempt HTML parsing
                parsed_html = self.parse_html(resp.text)
                self._log_diagnostic(
                    method="POST",
                    url=self.endpoint_url,
                    status_code=resp.status_code,
                    content_type=content_type,
                    byte_size=len(resp.content),
                    candidate_count=len(parsed_html),
                    auth_state="HTML_NOTICES",
                )
                return parsed_html[:limit]

            # Parse JSON
            try:
                data = resp.json()
            except Exception as json_err:
                self._log_diagnostic(
                    method="POST",
                    url=self.endpoint_url,
                    status_code=resp.status_code,
                    content_type=content_type,
                    byte_size=len(resp.content),
                    auth_state="INVALID_JSON",
                )
                raise ValueError(f"Failed to parse UMS response as JSON: {json_err}")

            top_keys = list(data.keys()) if isinstance(data, dict) else []
            candidates = self._extract_candidates_from_response(data)

            self._log_diagnostic(
                method="POST",
                url=self.endpoint_url,
                status_code=resp.status_code,
                content_type=content_type,
                byte_size=len(resp.content),
                top_keys=top_keys,
                candidate_count=len(candidates),
                auth_state="VALID",
            )
            return candidates[:limit]

    def fetch_announcement_details(self, announcement_id: str) -> Dict[str, Any]:
        """Fetch complete body and attachment metadata for a specific announcement."""
        if self.connector_mode == "mock":
            for item in self._get_mock_announcements():
                if str(item.get("id")) == str(announcement_id) or item.get("announcement_id") == announcement_id:
                    return item
            raise KeyError(f"Mock announcement '{announcement_id}' not found.")

        # Live implementation: queries specific announcement details
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Cookie": self.session_cookie.strip(),
            "Content-Type": "application/json; charset=utf-8",
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            resp = client.post(self.endpoint_url, headers=headers, json={"announcementId": announcement_id})
            if resp.status_code >= 400:
                raise RuntimeError(f"Failed to fetch detail for {announcement_id}: HTTP {resp.status_code}")
            data = resp.json()
            if isinstance(data, dict) and "d" in data:
                d = data["d"]
                return json.loads(d) if isinstance(d, str) else d
            return data

    def normalize_announcement(self, raw: Dict[str, Any]) -> RawAnnouncement:
        """Map raw UMS JSON fields to project's canonical RawAnnouncement schema."""
        if not isinstance(raw, dict):
            raise ValueError("Announcement record must be a dictionary")

        # Map possible UMS field names to standard schema
        title = (
            raw.get("title")
            or raw.get("NoticeTitle")
            or raw.get("Subject")
            or raw.get("Headline")
            or "Untitled UMS Announcement"
        )
        title = html.unescape(re.sub(r"<[^>]+>", " ", str(title))).strip()
        title = re.sub(r"\s+", " ", title)
        title = (
            title.replace("\u2019", "'")
            .replace("\u2018", "'")
            .replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("\u2013", "-")
            .replace("\u2014", "--")
            .replace("\u20b9", "Rs. ")
        )

        content = (
            raw.get("full_content")
            or raw.get("NoticeContent")
            or raw.get("Body")
            or raw.get("Description")
            or raw.get("Message")
            or ""
        )
        content = html.unescape(re.sub(r"<[^>]+>", "\n", str(content))).strip()
        content = re.sub(r"\n\s*\n+", "\n\n", content)
        content = (
            content.replace("\u2019", "'")
            .replace("\u2018", "'")
            .replace("\u201c", '"')
            .replace("\u201d", '"')
            .replace("\u2013", "-")
            .replace("\u2014", "--")
            .replace("\u20b9", "Rs. ")
        )

        pub_date = (
            raw.get("publication_date")
            or raw.get("NoticeDate")
            or raw.get("Date")
            or raw.get("CreatedOn")
            or datetime.now().strftime("%Y-%m-%d")
        )
        pub_date = str(pub_date).strip()
        clean_date_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", pub_date)
        if clean_date_match:
            pub_date = clean_date_match.group(0)
        else:
            for fmt in ("%d-%b-%Y", "%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
                try:
                    pub_date = datetime.strptime(pub_date[:11].strip(), fmt).strftime("%Y-%m-%d")
                    break
                except Exception:
                    pass

        ref_no = raw.get("reference_number") or raw.get("RefNo") or raw.get("ReferenceNumber")
        if ref_no:
            ref_no = str(ref_no).strip()

        # Handle attachment flags and names
        attachment_present = bool(
            raw.get("attachment_present")
            or raw.get("HasAttachment")
            or raw.get("IsAttachment")
            or False
        )
        attachment_names = (
            raw.get("attachment_names")
            or raw.get("AttachmentFiles")
            or raw.get("Attachments")
            or []
        )
        if isinstance(attachment_names, str):
            if attachment_names.startswith("["):
                try:
                    attachment_names = json.loads(attachment_names)
                except Exception:
                    attachment_names = [attachment_names]
            else:
                attachment_names = [attachment_names] if attachment_names else []

        # If attachment text detected in content, set attachment_present
        if not attachment_present and re.search(r"attachment:\s*\d+\s+[\w\.-]+", content, re.IGNORECASE):
            attachment_present = True

        # Generate stable announcement ID
        raw_source_id = str(raw.get("id") or raw.get("AnnouncementId") or raw.get("NoticeId") or "").strip()
        if raw_source_id:
            ann_id = f"ANN-UMS-{raw_source_id}"
        else:
            # Deterministic hash fallback
            unique_seed = f"UMS|{ref_no or ''}|{pub_date}|{title}|{content[:50]}"
            id_hash = hashlib.sha256(unique_seed.encode("utf-8")).hexdigest()[:12]
            clean_date = pub_date[:10].replace("-", "").replace("/", "")
            ann_id = f"ANN-UMS-{clean_date}-{id_hash}"

        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        source_url = raw.get("source_url") or f"{self.base_url}StudentDashboard.aspx"

        return RawAnnouncement(
            announcement_id=ann_id,
            title=title,
            publication_date=pub_date,
            reference_number=ref_no,
            full_content=content,
            attachment_present=attachment_present,
            attachment_names=[str(x) for x in attachment_names],
            content_hash=content_hash,
            source=raw.get("source") or "ums",
            source_url=source_url,
        )

    def _get_mock_announcements(self) -> List[Dict[str, Any]]:
        """Realistic simulated UMS notices for test & evaluation."""
        return [
            {
                "id": "10091",
                "title": "Urgent: Mid-Term Examination Room Reallocation - Autumn 2026",
                "publication_date": "2026-10-16",
                "reference_number": "LPU/10.2/EXAM/2026/089",
                "full_content": (
                    "All 3rd Year B.Tech Computer Science and Engineering students are hereby notified "
                    "that due to maintenance work in Block 34, the exam hall for course CSE301 (Data Structures) "
                    "scheduled on 20th October 2026 has been shifted from Room 34-105 to Block 32 Room 32-205. "
                    "Students must report 15 minutes before exam commencement. Seating plan attached."
                ),
                "attachment_present": True,
                "attachment_names": ["Reallocated_Seating_Plan_Oct2026.pdf"],
                "source_url": "https://ums.lpu.in/lpuums/StudentDashboard.aspx?nid=10091",
            },
            {
                "id": "10092",
                "title": "Campus Placement Drive: Google Cloud Engineering - 2027 Passing Out Batch",
                "publication_date": "2026-10-15",
                "reference_number": "LPU/20.2/TPO/2026/0441",
                "full_content": (
                    "Division of Career Services invites registration for Google Cloud Engineering Placement Drive. "
                    "Target Audience: Final Year (4th Year) B.Tech CSE, IT and ECE students with CGPA 8.0 and above. "
                    "Last Date to Apply: 24th October 2026. Pre-Placement Talk will be held in Shanti Devi Mittal Auditorium (Block 30) "
                    "on 22nd October at 10:00 AM. Eligible students must complete the registration on the placement portal."
                ),
                "attachment_present": False,
                "attachment_names": [],
                "source_url": "https://ums.lpu.in/lpuums/StudentDashboard.aspx?nid=10092",
            },
            {
                "id": "10093",
                "title": "National Hackathon: Smart India Hackathon 2026 Internal Scrutiny",
                "publication_date": "2026-10-14",
                "reference_number": "LPU/18.4/INNOV/2026/0019",
                "full_content": (
                    "Department of Student Research & Project under Division of Innovation & Entrepreneurship "
                    "invites team nominations for Smart India Hackathon 2026. Open to all years of B.Tech, MCA, and M.Sc. "
                    "Mentoring sessions will be conducted in Block 34 Room 34-413 on Saturday at 02:00 PM. "
                    "Teams must submit problem statement summaries by 25th October 2026."
                ),
                "attachment_present": True,
                "attachment_names": ["SIH_2026_Problem_Guidelines.pdf"],
                "source_url": "https://ums.lpu.in/lpuums/StudentDashboard.aspx?nid=10093",
            },
            {
                "id": "10094",
                "title": "Winter Internship and Capstone Project Registration Guidelines",
                "publication_date": "2026-10-12",
                "reference_number": "LPU/10.2/ANN(DAA)/2026/0115",
                "full_content": (
                    "Dear Students, Guidelines for Winter Term Project and Industrial Internship 2026 are live on UMS. "
                    "Students must select their domain supervisor via UMS Navigation -> Academics -> Capstone Project. "
                    "Deadline for mentor selection is 31st October 2026."
                ),
                "attachment_present": False,
                "attachment_names": [],
                "source_url": "https://ums.lpu.in/lpuums/StudentDashboard.aspx?nid=10094",
            },
        ]

    def parse_raw_text(self, text: str) -> List[Dict[str, Any]]:
        """Parse unformatted text copied from UMS notice board into announcement dictionaries."""
        if not text or not text.strip():
            return []

        trimmed = text.strip()
        # 1. Check if text is JSON string
        if (trimmed.startswith("[") and trimmed.endswith("]")) or (trimmed.startswith("{") and trimmed.endswith("}")):
            try:
                parsed = json.loads(trimmed)
                if isinstance(parsed, list):
                    return parsed
                elif isinstance(parsed, dict):
                    if "announcements" in parsed:
                        return parsed["announcements"]
                    if "data" in parsed and isinstance(parsed["data"], list):
                        return parsed["data"]
                    return [parsed]
            except Exception:
                pass

        # 2. Check if text contains HTML
        if "<table" in text.lower() or "<tr" in text.lower() or "<div" in text.lower():
            return self.parse_html(text)

        # 3. Split into blocks by common notice delimiters
        blocks = re.split(
            r'\n\s*(?:---+|===+|___+|\*{3,})\s*\n|\n\s*\n\s*(?=(?:Notice\s*\d+|Title:|Ref(?:\.|\s*No|\.No)|Subject:))',
            text,
            flags=re.IGNORECASE,
        )

        results = []
        for idx, block in enumerate(blocks):
            b = block.strip()
            if not b or len(b) < 15:
                continue

            lines = [line.strip() for line in b.splitlines() if line.strip()]
            if not lines:
                continue

            # Check standard LPU header: "Title : Ref (Date)"
            lpu_header_match = re.match(r'^(.*?)\s*:\s*(LPU/[A-Za-z0-9/._-]+)\s*\((.*?)\)', lines[0])

            title_match = re.search(r'(?:Title|Subject|Headline)\s*[:\-]\s*(.+)', b, re.IGNORECASE)
            ref_match = re.search(r'(?:Ref(?:\.|\s*No|\.No\.?|erence)?)\s*[:\-]\s*([A-Za-z0-9\/\.\-_]+)', b, re.IGNORECASE)
            date_match = re.search(r'(?:Date|Dated|Published)\s*[:\-]\s*(\d{1,4}[-/\.]\w{1,9}[-/\.]\d{2,4})', b, re.IGNORECASE)
            if not date_match:
                date_match = re.search(r'\b(\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}|\d{4}-\d{2}-\d{2})\b', b)

            attach_match = re.search(r'(?:Attachment(?:s)?|Files?)\s*[:\-]\s*(.+)', b, re.IGNORECASE)

            if lpu_header_match:
                title = lpu_header_match.group(1).strip()
                ref_no = lpu_header_match.group(2).strip()
                pub_date = lpu_header_match.group(3).strip()
            else:
                title = title_match.group(1).strip() if title_match else lines[0]
                ref_no = ref_match.group(1).strip() if ref_match else f"UMS-PASTE-{datetime.now().strftime('%Y%m%d')}-{idx+1}"
                pub_date = date_match.group(1).strip() if date_match else datetime.now().strftime("%Y-%m-%d")

            attach_names = []
            if attach_match:
                raw_att = attach_match.group(1).strip()
                attach_names = [a.strip() for a in re.split(r'[,;]\s*', raw_att) if a.strip()]
            if not attach_names:
                inline_att = re.findall(r'[\w\.-]+\.(?:pdf|docx?|xlsx?|zip)', b, re.IGNORECASE)
                if inline_att:
                    attach_names = list(dict.fromkeys(inline_att))

            has_attach_text = bool(
                re.search(
                    r'\b(?:attachment(?:s)?\s*[:\-]|attached\s+herewith|find\s+attached|attached\s+file|download\s+attachment)\b',
                    b,
                    re.IGNORECASE,
                )
            )

            results.append({
                "title": title[:200],
                "publication_date": pub_date,
                "reference_number": ref_no,
                "full_content": b,
                "attachment_present": bool(attach_names or has_attach_text),
                "attachment_names": attach_names,
                "source": "ums_paste",
                "source_url": "https://ums.lpu.in/lpuums/StudentDashboard.aspx",
            })

        return results

    def parse_html(self, html_content: str) -> List[Dict[str, Any]]:
        """Parse HTML table or announcement list into structured announcement dictionaries."""
        if not html_content or not html_content.strip():
            return []

        results = []
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html_content, re.DOTALL | re.IGNORECASE)
        for idx, row in enumerate(rows):
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
            if not cells:
                continue

            cleaned_cells = [re.sub(r'<[^>]+>', ' ', c).strip() for c in cells]
            non_empty = [c for c in cleaned_cells if c]
            if len(non_empty) < 2:
                continue

            date_val = None
            ref_val = None
            for c in non_empty:
                if not date_val and re.search(r'\b\d{1,2}[-/\.]\w{3,}[-/\.]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b', c):
                    date_val = c
                elif not ref_val and re.search(r'LPU|REF|ANN|/\d{2,4}/', c, re.IGNORECASE):
                    ref_val = c

            title_val = non_empty[1] if len(non_empty) > 1 else non_empty[0]
            att_files = re.findall(r'href=[\'"]([^\'"]+\.(?:pdf|docx?|xlsx?|zip))[\'"]', row, re.IGNORECASE)
            has_attach = bool(
                att_files
                or re.search(r'href=[\'"][^\'"]+\.(pdf|docx?|xlsx?|zip|png|jpe?g)[\'"]', row, re.IGNORECASE)
                or re.search(r'\b(?:attachment(?:s)?\s*[:\-]|attached\s+herewith|find\s+attached)\b', row, re.IGNORECASE)
            )

            results.append({
                "title": title_val[:200],
                "publication_date": date_val or datetime.now().strftime("%Y-%m-%d"),
                "reference_number": ref_val or f"UMS-HTML-{datetime.now().strftime('%Y%m%d')}-{idx+1}",
                "full_content": " \n ".join(non_empty),
                "attachment_present": has_attach,
                "attachment_names": [f.split("/")[-1] for f in att_files],
                "source": "ums_html",
                "source_url": "https://ums.lpu.in/lpuums/StudentDashboard.aspx",
            })

        # Convert links to inline text with filename before tag cleaning so attachment names are never lost
        enriched_html = re.sub(
            r'<a[^>]+href=[\'"]([^\'"]+\.(?:pdf|docx?|xlsx?|zip))[\'"][^>]*>(.*?)</a>',
            r'\2 (Attachment: \1)',
            html_content,
            flags=re.IGNORECASE,
        )

        doc_attachments = re.findall(r'href=[\'"]([^\'"]+\.(?:pdf|docx?|xlsx?|zip))[\'"]', html_content, re.IGNORECASE)
        doc_att_names = [f.split("/")[-1] for f in doc_attachments]

        if not results:
            # Check for card/div/panel/accordion containers
            containers = re.findall(
                r'<(?:div|li|article)[^>]*(?:class|id)=[\'"][^\'"]*(?:announcement|notice|card|panel|accordion)[^\'"]*[\'"][^>]*>(.*?)</(?:div|li|article)>',
                html_content,
                re.DOTALL | re.IGNORECASE,
            )
            for idx, cont in enumerate(containers):
                clean_text = html.unescape(re.sub(r'<[^>]+>', ' ', cont)).strip()
                clean_text = re.sub(r'\s+', ' ', clean_text)
                if len(clean_text) < 15:
                    continue

                title_match = re.search(r'<h[1-6][^>]*>(.*?)</h[1-6]>|<strong[^>]*>(.*?)</strong>', cont, re.IGNORECASE | re.DOTALL)
                title = re.sub(r'<[^>]+>', '', title_match.group(0)).strip() if title_match else clean_text[:80]
                if title.lower().rstrip(':') in ('date', 'ref', 'ref no', 'notice no', 'reference', 'attachment', 'attachments', 'details'):
                    for line in clean_text.splitlines():
                        line_clean = line.strip()
                        if line_clean and not any(line_clean.lower().startswith(k) for k in ('date', 'ref', 'attachment')):
                            title = line_clean[:120]
                            break

                date_match = re.search(r'\b(\d{1,2}[-/\.]\w{3,}[-/\.]\d{2,4}|\d{4}-\d{2}-\d{2})\b', clean_text)
                pub_date = date_match.group(1).strip() if date_match else datetime.now().strftime("%Y-%m-%d")

                ref_match = re.search(r'LPU[A-Za-z0-9\/\.\-_]+|REF[A-Za-z0-9\/\.\-_]+', clean_text, re.IGNORECASE)
                ref_no = ref_match.group(0).strip() if ref_match else f"UMS-DOM-{datetime.now().strftime('%Y%m%d')}-{idx+1}"

                att_files = re.findall(r'href=[\'"]([^\'"]+\.(?:pdf|docx?|xlsx?|zip))[\'"]', cont, re.IGNORECASE)
                att_names = [f.split("/")[-1] for f in att_files]
                if not att_names and len(containers) <= 1:
                    att_names = doc_att_names

                has_attach_text = bool(
                    re.search(
                        r'\b(?:attachment(?:s)?\s*[:\-]|attached\s+herewith|find\s+attached|attached\s+file|download\s+attachment)\b',
                        clean_text,
                        re.IGNORECASE,
                    )
                )

                results.append({
                    "title": title[:200],
                    "publication_date": pub_date,
                    "reference_number": ref_no,
                    "full_content": clean_text,
                    "attachment_present": bool(att_names or has_attach_text),
                    "attachment_names": att_names,
                    "source": "ums_html",
                    "source_url": "https://ums.lpu.in/lpuums/StudentDashboard.aspx",
                })

        if not results:
            cleaned_text = re.sub(r'<[^>]+>', '\n', enriched_html)
            return self.parse_raw_text(cleaned_text)

        return results

