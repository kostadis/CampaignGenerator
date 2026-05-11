#!/usr/bin/env python3
"""Scabard API client — shareable Python SDK for scabard.com.

Wraps the Scabard REST API (https://www.scabard.com/api/v0).
Only dependency: requests.

Usage:
    from scabard_client import ScabardClient, ScabardAuthError

    client = ScabardClient(username="you", access_key="your-key")
    campaigns = client.list_campaigns()

    ok, thing_id = client.create_page(
        campaign_id=121,
        concept="character",
        name="Grundar Quartzvein",
        brief_summary="Dwarven blacksmith and reluctant informant.",
        description="...",
        secrets="Working for the Kraken Society.",
    )
"""

import time

import requests

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


# ── Client ────────────────────────────────────────────────────────────────────


class ScabardClient:
    """Client for the Scabard API (https://www.scabard.com/api/v0).

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

    def _get(self, url: str) -> dict:
        last_exc: Exception | None = None
        for attempt in range(4):
            resp = requests.get(url, headers=self._headers(), timeout=self._timeout)
            if resp.status_code == 429:
                wait = 5 * (2 ** attempt)
                time.sleep(wait)
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

    def _post(self, url: str, payload: dict) -> dict:
        """POST with exponential-backoff retry on 429 (rate limited).

        Attempts: 4 total. Wait schedule: 5s, 10s, 20s, 40s.
        Raises ScabardRateLimitError if all attempts are exhausted.
        """
        headers = {**self._headers(), "content-type": "application/json"}
        last_exc: Exception | None = None
        for attempt in range(4):
            resp = requests.post(url, headers=headers, json=payload,
                                 timeout=self._timeout)
            if resp.status_code == 429:
                wait = 5 * (2 ** attempt)
                time.sleep(wait)
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

    # ── Campaign endpoints ────────────────────────────────────────────────────

    def list_campaigns(self) -> list[dict]:
        """Return a list of all campaigns the user is GM of.

        Returns:
            List of campaign summary dicts (id, name, etc.).
        """
        data = self._get(f"{self.BASE_URL}/campaign")
        return data.get("rows", [])

    def get_campaign(self, campaign_id: int) -> dict:
        """Return details for one campaign plus a summary of every page in it.

        Returns:
            Dict with keys:
              "main" — campaign details dict
              "rows" — list of page summary dicts
        """
        return self._get(f"{self.BASE_URL}/campaign/{campaign_id}")

    # ── Page endpoints ────────────────────────────────────────────────────────

    def list_pages(self, campaign_id: int, concept: str) -> list[dict]:
        """Return all pages of a given concept in the campaign.

        Args:
            campaign_id: Campaign ID.
            concept:     Page type — "character", "group", "location",
                         "event", etc. Must be lowercase.

        Returns:
            List of page summary dicts.
        """
        data = self._get(f"{self.BASE_URL}/campaign/{campaign_id}/{concept}")
        return data.get("rows", [])

    def get_page(self, campaign_id: int, concept: str, thing_id: int) -> dict:
        """Return details for a specific page.

        Args:
            campaign_id: Campaign ID.
            concept:     Page concept (lowercase).
            thing_id:    Page ID.

        Returns:
            Page detail dict (under "main" in the raw API response).
        """
        data = self._get(
            f"{self.BASE_URL}/campaign/{campaign_id}/{concept}/{thing_id}"
        )
        return data.get("main", data)

    def fetch_existing(self, campaign_id: int, concept: str) -> dict[str, int]:
        """Return a name → thing_id mapping for all existing pages of a concept.

        Useful for checking whether a page already exists before creating one.

        Args:
            campaign_id: Campaign ID.
            concept:     Page concept (lowercase).

        Returns:
            Dict mapping page name (str) to page ID (int).
        """
        rows = self.list_pages(campaign_id, concept)
        result: dict[str, int] = {}
        for row in rows:
            name = row.get("name")
            uri = row.get("uri", "")
            if not name or not uri:
                continue
            try:
                # uri is like /campaign/{id}/{concept}/{thing_id}
                thing_id = int(uri.rstrip("/").rsplit("/", 1)[-1])
                result[name] = thing_id
            except (ValueError, IndexError):
                pass
        return result

    def create_page(
        self,
        campaign_id: int,
        concept: str,
        name: str,
        brief_summary: str = "",
        description: str = "",
        secrets: str = "",
        gm_secrets: str = "",
        is_secret: bool = False,
    ) -> tuple[bool, int | None]:
        """Create a new page in the campaign.

        Because the Scabard API does not return the new page's ID in the
        create response, this method re-fetches the page list after a
        successful create to discover it.

        Args:
            campaign_id:   Campaign ID.
            concept:       Page concept (lowercase): "character", "group",
                           "location", "event", etc.
            name:          Page name (must be unique within the concept).
            brief_summary: Short player-facing summary (1-2 sentences).
            description:   Full player-facing markdown body.
            secrets:       GM-only text hidden from players.
            gm_secrets:    Additional GM-only notes.
            is_secret:     Whether to mark the page as secret.

        Returns:
            (True, thing_id)  — created; thing_id is the new page's ID.
            (True, None)      — created but ID could not be discovered.
            (False, None)     — API reported isSuccess=False.
        """
        payload = {
            "name": name,
            "briefSummary": brief_summary,
            "description": description,
            "secrets": secrets,
            "gmSecrets": gm_secrets,
            "isSecret": "true" if is_secret else "false",
            # URL uses lowercase concept; body field requires title case
            "concept": concept.title(),
        }
        result = self._post(
            f"{self.BASE_URL}/campaign/{campaign_id}/{concept}", payload
        )
        if not result.get("isSuccess", False):
            return False, None

        # The API does not return the new page's ID — re-fetch the list to
        # discover it. A brief pause avoids a race where the page isn't yet
        # visible in the list endpoint.
        time.sleep(1)
        existing = self.fetch_existing(campaign_id, concept)
        return True, existing.get(name)

    def update_page(
        self,
        campaign_id: int,
        concept: str,
        thing_id: int,
        name: str,
        brief_summary: str = "",
        description: str = "",
        secrets: str = "",
        gm_secrets: str = "",
        is_secret: bool = False,
    ) -> bool:
        """Update an existing page.

        Args:
            campaign_id:   Campaign ID.
            concept:       Page concept (lowercase).
            thing_id:      Page ID to update.
            name:          Page name.
            brief_summary: Short player-facing summary.
            description:   Full player-facing markdown body.
            secrets:       GM-only text.
            gm_secrets:    Additional GM-only notes.
            is_secret:     Whether to mark the page as secret.

        Returns:
            True if the API reported isSuccess=True, False otherwise.
        """
        payload = {
            "name": name,
            "briefSummary": brief_summary,
            "description": description,
            "secrets": secrets,
            "gmSecrets": gm_secrets,
            "isSecret": "true" if is_secret else "false",
            # URL uses lowercase concept; body field requires title case
            "concept": concept.title(),
        }
        result = self._post(
            f"{self.BASE_URL}/campaign/{campaign_id}/{concept}/{thing_id}",
            payload,
        )
        return bool(result.get("isSuccess", False))

    # ── Connection-type endpoints ─────────────────────────────────────────────

    def list_connection_types(self, concept: str) -> list[dict]:
        """Return the catalog of valid connection types for a concept.

        Connection types are shared across all campaigns — the URL has no
        campaign_id. Each entry describes a directed relationship from a
        source concept to a target concept. Every entry returned by the
        live API (226 sampled across character/place/event/group) included
        ``isSymmetric``; the docs example shows it omitted on some entries,
        so callers should treat a missing key as False defensively.

        ``source`` matches the URL concept on every live entry observed
        (e.g. ``/conntypes/character`` returns only entries with
        ``source: "Character"``).

        Args:
            concept: Source concept (lowercase): "character", "group",
                     "place", "event", etc.

        Returns:
            List of connection-type dicts with keys:
              "rel"         — relationship label (e.g. "Acquaintance of")
              "source"      — source concept, Title Case (matches URL concept)
              "target"      — target concept, Title Case ("Event", "Place", ...)
              "isSymmetric" — bool; treat missing as False (defensive)
              "postParam"   — undocumented; e.g. "acquaintance_of:character".
                              Looks like the parameter token a future
                              connection-CRUD endpoint would accept. Not used
                              by the SDK; surfaced here for callers who want
                              to experiment.
        """
        data = self._get(f"{self.BASE_URL}/campaign/conntypes/{concept}")
        return data.get("connTypes", [])

    def create_connections(
        self,
        campaign_id: int,
        concept: str,
        thing_id: int,
        connections: dict[str, str],
    ) -> tuple[bool, dict[str, dict]]:
        """Create one or more connections from a page to other pages by name.

        Posts to ``/campaign/{id}/{concept}/{thing_id}/connect``. Targets are
        resolved server-side by exact name match — the value of each entry
        in ``connections`` is the target page's name, not its thing_id. The
        endpoint accepts multiple connections in a single call.

        Args:
            campaign_id: Campaign ID.
            concept:     Source page concept (lowercase) — e.g. "character".
            thing_id:    Source page ID.
            connections: Mapping of ``{postParam: target_page_name}``. The
                         postParam strings come from
                         ``list_connection_types(concept)`` and look like
                         ``"mother_of:character"`` or ``"home:place"``.
                         Multiple entries OK; all are sent in one request.

        Returns:
            ``(isSuccess, {postParam: connection_record})``. Each record is
            the raw API dict and contains:

              * ``relId``    — int connection ID (use to identify the edge)
              * ``uri``      — path to the target page
              * ``value``    — the resolved target page name
              * ``isFormer`` — bool (always False on a fresh create)
              * ``isSecret`` — bool (always False on a fresh create; the
                               request shape for setting it is not documented)

        Notes:
            * Despite the official docs showing ``-d key=value`` form pairs,
              the live endpoint only accepts a JSON body — form-encoded
              requests return ``200 {"isSuccess": false}`` silently. The SDK
              sends JSON (verified empirically 2026-05-10).
            * The body's ``concept`` field is Title-cased automatically, same
              convention as ``create_page`` / ``update_page``.
            * The API does not (yet) expose update / delete / list-existing
              connection endpoints. The returned ``relId`` is the only handle
              for an edge, so callers wanting to track edges should persist
              the response.
        """
        payload: dict = {"concept": concept.title(), **connections}
        result = self._post(
            f"{self.BASE_URL}/campaign/{campaign_id}/{concept}/{thing_id}/connect",
            payload,
        )
        ok = bool(result.get("isSuccess", False))
        records = {
            k: v for k, v in result.items()
            if k != "isSuccess" and isinstance(v, dict)
        }
        return ok, records
