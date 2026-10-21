#!/usr/bin/env python3
"""Scabard API client — shareable Python SDK for scabard.com.

Wraps the Scabard REST API (https://www.scabard.com/api/v0).
Only dependency: requests.

Usage:
    from scabard_sdk import ScabardClient

    client = ScabardClient(username="you", access_key="your-key")
    for campaign in client.list_campaigns():
        print(campaign.id, campaign.name)

    thing_id = client.create_page(
        121, "character", "Grundar Quartzvein",
        brief_summary="Dwarven blacksmith and reluctant informant.",
        aliases=["Grundar"],
    )
    client.update_page(121, "character", thing_id,
                       secrets="Working for the Kraken Society.")
    page = client.get_page(121, "character", thing_id)
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import time

import requests

# ── Concepts ──────────────────────────────────────────────────────────────────

# The official concept list (API docs, "Concept (or Page Type)"). URLs use the
# lowercase form; values in request and response bodies are Title Case.
CONCEPTS = (
    "character", "place", "group", "item", "event",
    "vehicle", "category", "attribute", "note", "folder",
)

# Names used by older code and third-party docs that the API rejects with 404.
_RENAMED_CONCEPTS = {"location": "place"}


def normalize_concept(concept: str) -> str:
    """Return the lowercase URL form of a concept, or raise ValueError."""
    c = concept.strip().lower()
    if c in CONCEPTS:
        return c
    if c in _RENAMED_CONCEPTS:
        raise ValueError(
            f"Unknown Scabard concept {concept!r}; the API calls it "
            f"{_RENAMED_CONCEPTS[c]!r}."
        )
    raise ValueError(
        f"Unknown Scabard concept {concept!r}; expected one of {', '.join(CONCEPTS)}."
    )


# ── Exceptions ────────────────────────────────────────────────────────────────


class ScabardError(Exception):
    """Base class for all Scabard API errors."""

    def __init__(self, message: str, status_code: int = 0, detail: str = "") -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail


class ScabardAuthError(ScabardError):
    """401 — invalid username or access key, or key has expired."""


class ScabardForbiddenError(ScabardError):
    """403 — authenticated but no access to the requested resource."""


class ScabardNotFoundError(ScabardError):
    """404 — resource does not exist."""


class ScabardRateLimitError(ScabardError):
    """429 — rate limit exhausted after all retries."""


class ScabardRequestError(ScabardError):
    """200 with ``isSuccess: false`` — the API refused the write.

    The API gives no reason. ``response`` holds the full response body.
    """

    def __init__(self, message: str, response: dict) -> None:
        super().__init__(message, status_code=200, detail=str(response))
        self.response = response


# ── Data types ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PageRef:
    """Identifies one page: ``/campaign/{campaign_id}/{concept}/{thing_id}``."""

    campaign_id: int
    concept: str
    thing_id: int

    @classmethod
    def from_uri(cls, uri: str) -> "PageRef":
        parts = uri.strip("/").split("/")
        if len(parts) != 4 or parts[0] != "campaign":
            raise ValueError(f"Not a Scabard page uri: {uri!r}")
        return cls(int(parts[1]), parts[2].lower(), int(parts[3]))

    @property
    def uri(self) -> str:
        return f"/campaign/{self.campaign_id}/{self.concept}/{self.thing_id}"


@dataclass(frozen=True)
class Campaign:
    id: int
    name: str
    raw: dict = field(repr=False, compare=False)


@dataclass(frozen=True)
class Connection:
    """One edge from a page, as listed in the page's ``conns``.

    The read side carries no ``relId``; edges are identified by
    ``(rel, target)``.
    """

    rel: str            # e.g. "Acquaintance of"
    explicit: str       # e.g. "Is Acquaintance of"
    target: PageRef
    target_name: str
    is_secret: bool


@dataclass
class Page:
    ref: PageRef
    name: str
    brief_summary: str
    description: str
    secrets: str
    gm_secrets: str
    is_secret: bool
    aliases: list[str]
    last_edited: datetime | None
    connections: list[Connection]
    raw: dict = field(repr=False)


def parse_aliases(value: str | None) -> list[str]:
    """Split the API's comma-separated alias string into names."""
    return [a.strip() for a in (value or "").split(",") if a.strip()]


def _format_aliases(aliases: list[str]) -> str:
    for a in aliases:
        if "," in a:
            raise ValueError(f"Alias {a!r} contains a comma; the API separates aliases with commas.")
    return ", ".join(a.strip() for a in aliases if a.strip())


# ── Client ────────────────────────────────────────────────────────────────────


class ScabardClient:
    """Client for the Scabard API (https://www.scabard.com/api/v0).

    Every method that takes a ``concept`` validates it against ``CONCEPTS``
    and raises ValueError for anything else (including the old ``location``).
    Writes raise ScabardRequestError when the API answers ``isSuccess: false``.

    Args:
        username:   Your Scabard username.
        access_key: API access key from your profile page. Expires 24 hours
                    after generation — prompt your users to regenerate if
                    they receive ScabardAuthError.
        timeout:    HTTP request timeout in seconds (default 30).
    """

    BASE_URL = "https://www.scabard.com/api/v0"

    def __init__(self, username: str, access_key: str, timeout: int = 30) -> None:
        self._username = username
        self._access_key = access_key
        self._timeout = timeout

    # ── Private HTTP helpers ──────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {"username": self._username, "accessKey": self._access_key}

    def _raise_for_status(self, resp: requests.Response) -> None:
        """Convert HTTP error codes to typed exceptions."""
        if resp.status_code == 401:
            raise ScabardAuthError(
                "Invalid username or access key (key may have expired — "
                "keys expire 24 hours after generation).",
                status_code=401,
                detail=resp.text,
            )
        if resp.status_code == 403:
            raise ScabardForbiddenError(
                f"Access denied to {resp.url}",
                status_code=403,
                detail=resp.text,
            )
        if resp.status_code == 404:
            raise ScabardNotFoundError(
                f"Resource not found: {resp.url}",
                status_code=404,
                detail=resp.text,
            )
        if resp.status_code >= 500:
            raise ScabardError(
                f"Scabard server error {resp.status_code}: {resp.url}",
                status_code=resp.status_code,
                detail=resp.text,
            )
        resp.raise_for_status()

    def _request(self, method: str, url: str, payload: dict | None = None) -> dict:
        """Send a request with exponential-backoff retry on 429.

        Attempts: 4 total. Wait schedule: 5s, 10s, 20s, 40s.
        Raises ScabardRateLimitError if all attempts are exhausted.

        Bodies are always JSON: the live API rejects the form-encoded bodies
        its docs show (``/connect`` answers ``isSuccess: false``; page saves
        answer 500).
        """
        headers = self._headers()
        if payload is not None:
            headers["content-type"] = "application/json"
        last_exc: Exception | None = None
        for attempt in range(4):
            resp = requests.request(method, url, headers=headers, json=payload,
                                    timeout=self._timeout)
            if resp.status_code == 429:
                time.sleep(5 * (2 ** attempt))
                last_exc = ScabardRateLimitError(
                    "Rate limit exceeded.",
                    status_code=429,
                    detail=resp.text,
                )
                continue
            self._raise_for_status(resp)
            return resp.json()
        raise last_exc or ScabardRateLimitError("Rate limit exceeded after 4 retries.",
                                                status_code=429)

    def _get(self, url: str) -> dict:
        return self._request("GET", url)

    def _post(self, url: str, payload: dict) -> dict:
        """POST a write and raise ScabardRequestError on ``isSuccess: false``."""
        result = self._request("POST", url, payload)
        if not result.get("isSuccess", False):
            raise ScabardRequestError(f"Scabard rejected the write to {url}", result)
        return result

    def _page_url(self, campaign_id: int, concept: str, thing_id: int | None = None) -> str:
        url = f"{self.BASE_URL}/campaign/{campaign_id}/{normalize_concept(concept)}"
        return url if thing_id is None else f"{url}/{thing_id}"

    # ── Campaign endpoints ────────────────────────────────────────────────────

    def list_campaigns(self) -> list[Campaign]:
        """Return every campaign the user is GM of."""
        data = self._get(f"{self.BASE_URL}/campaign")
        campaigns = []
        for row in data.get("rows", []):
            uri = row.get("uri", "")
            try:
                campaign_id = int(uri.rstrip("/").rsplit("/", 1)[-1])
            except ValueError:
                continue
            campaigns.append(Campaign(id=campaign_id, name=row.get("name", ""), raw=row))
        return campaigns

    def get_campaign(self, campaign_id: int) -> dict:
        """Return the raw campaign response.

        Keys: ``main`` (campaign details) and ``rows`` (a summary of every
        page, each with ``name``, ``concept``, ``uri``, ``aliases``,
        ``briefSummary``, ``isSecret``).
        """
        return self._get(f"{self.BASE_URL}/campaign/{campaign_id}")

    # ── Page endpoints ────────────────────────────────────────────────────────

    def list_pages(self, campaign_id: int, concept: str) -> list[dict]:
        """Return the summary rows for every page of a concept."""
        return self._get(self._page_url(campaign_id, concept)).get("rows", [])

    def fetch_existing(self, campaign_id: int, concept: str) -> dict[str, int]:
        """Return a name → thing_id mapping for every page of a concept."""
        result: dict[str, int] = {}
        for row in self.list_pages(campaign_id, concept):
            name, uri = row.get("name"), row.get("uri", "")
            if not name or not uri:
                continue
            try:
                result[name] = PageRef.from_uri(uri).thing_id
            except ValueError:
                pass
        return result

    def get_page(self, campaign_id: int, concept: str, thing_id: int) -> Page:
        """Return one page, including its connections."""
        data = self._get(self._page_url(campaign_id, concept, thing_id))
        main = data.get("main", {})
        connections = []
        for c in data.get("conns", []):
            try:
                target = PageRef.from_uri(c.get("uri", ""))
            except ValueError:
                continue
            connections.append(Connection(
                rel=c.get("rel", ""),
                explicit=c.get("explicit", ""),
                target=target,
                target_name=c.get("name", ""),
                is_secret=bool(c.get("isSecret", False)),
            ))
        edited_ms = main.get("dateLastEditedUnix")
        return Page(
            ref=PageRef(campaign_id, normalize_concept(concept), thing_id),
            name=main.get("name", ""),
            brief_summary=main.get("briefSummary", ""),
            # rawDescription is the stored text; description has matched it on
            # every page sampled, but raw is the one to write back.
            description=main.get("rawDescription", main.get("description", "")),
            secrets=main.get("secrets", ""),
            gm_secrets=main.get("gmSecrets", ""),
            is_secret=bool(main.get("isSecret", False)),
            aliases=parse_aliases(main.get("aliases")),
            last_edited=(datetime.fromtimestamp(edited_ms / 1000, tz=timezone.utc)
                         if edited_ms else None),
            connections=connections,
            raw=data,
        )

    @staticmethod
    def _page_payload(concept: str, name: str, brief_summary: str, description: str,
                      secrets: str, gm_secrets: str, is_secret: bool,
                      aliases: list[str]) -> dict:
        return {
            "name": name,
            "briefSummary": brief_summary,
            "description": description,
            "secrets": secrets,
            "gmSecrets": gm_secrets,
            "isSecret": "true" if is_secret else "false",
            "aliases": _format_aliases(aliases),
            # URL uses lowercase concept; body field requires title case
            "concept": normalize_concept(concept).title(),
        }

    def create_page(
        self,
        campaign_id: int,
        concept: str,
        name: str,
        *,
        brief_summary: str = "",
        description: str = "",
        secrets: str = "",
        gm_secrets: str = "",
        is_secret: bool = False,
        aliases: list[str] = (),
    ) -> int | None:
        """Create a page and return its thing_id.

        The create response carries no id, so this re-fetches the page list
        and matches by name. Returns None if the new page could not be found
        (e.g. a second page already has the same name).

        Note: the API collapses newlines in text fields to spaces, so
        Markdown structure in ``description`` does not survive.
        """
        payload = self._page_payload(concept, name, brief_summary, description,
                                     secrets, gm_secrets, is_secret, list(aliases))
        self._post(self._page_url(campaign_id, concept), payload)
        # A brief pause avoids a race where the page isn't yet in the list.
        time.sleep(1)
        return self.fetch_existing(campaign_id, concept).get(name)

    def update_page(
        self,
        campaign_id: int,
        concept: str,
        thing_id: int,
        *,
        name: str | None = None,
        brief_summary: str | None = None,
        description: str | None = None,
        secrets: str | None = None,
        gm_secrets: str | None = None,
        is_secret: bool | None = None,
        aliases: list[str] | None = None,
    ) -> Page:
        """Change only the fields you pass; keep every other field as it is.

        Reads the page, overlays the given fields, and saves the whole page,
        so the result does not depend on how the server treats a missing
        field. Pass ``""`` (or ``[]`` for aliases) to clear a field.

        Returns the page as saved: the page that was read, with the changes
        applied. It is not re-read from the server.
        """
        page = self.get_page(campaign_id, concept, thing_id)
        changes = {
            "name": name, "brief_summary": brief_summary, "description": description,
            "secrets": secrets, "gm_secrets": gm_secrets, "is_secret": is_secret,
            "aliases": aliases,
        }
        for attr, value in changes.items():
            if value is not None:
                setattr(page, attr, list(value) if attr == "aliases" else value)
        payload = self._page_payload(concept, page.name, page.brief_summary,
                                     page.description, page.secrets, page.gm_secrets,
                                     page.is_secret, page.aliases)
        self._post(self._page_url(campaign_id, concept, thing_id), payload)
        return page

    # ── Connection endpoints ──────────────────────────────────────────────────

    def list_connection_types(self, concept: str) -> list[dict]:
        """Return the catalog of connection types whose source is ``concept``.

        Shared across all campaigns (no campaign_id in the URL). Each entry
        has ``rel``, ``source``, ``target`` (Title Case), ``isSymmetric`` and
        ``postParam`` — the key ``create_connections`` takes, formatted
        ``{snake_rel}:{lowercase_target}`` (e.g. ``"mother_of:character"``).
        """
        data = self._get(f"{self.BASE_URL}/campaign/conntypes/{normalize_concept(concept)}")
        return data.get("connTypes", [])

    def list_connections(self, campaign_id: int, concept: str, thing_id: int) -> list[Connection]:
        """Return a page's existing connections (from the page's ``conns``)."""
        return self.get_page(campaign_id, concept, thing_id).connections

    def create_connections(
        self,
        campaign_id: int,
        concept: str,
        thing_id: int,
        connections: dict[str, str],
    ) -> dict[str, dict]:
        """Create one or more connections from a page to other pages by name.

        Args:
            connections: ``{postParam: target_page_name}``. postParams come
                         from ``list_connection_types(concept)``. Targets are
                         resolved server-side by exact name and must exist.

        Returns:
            ``{postParam: record}``; each record has ``relId``, ``uri``,
            ``value`` (the resolved target name), ``isFormer``, ``isSecret``.

        The API has no update or delete for connections, and posting the same
        connection twice is not known to be idempotent: check
        ``list_connections`` first.
        """
        payload: dict = {"concept": normalize_concept(concept).title(), **connections}
        result = self._post(f"{self._page_url(campaign_id, concept, thing_id)}/connect", payload)
        return {k: v for k, v in result.items() if k != "isSuccess" and isinstance(v, dict)}
