#!/usr/bin/env python3
"""Integration tests for the Scabard API.

Verifies that every endpoint works as documented. Requires real credentials
and a campaign you own. Creates a temporary test page then marks it for
deletion (Scabard has no DELETE endpoint).

Usage:
    python test_scabard_api.py \\
        --username kostadis \\
        --access-key <key> \\
        --campaign-id 121

    # Use a specific concept (default: character):
    python test_scabard_api.py ... --concept location

    # Leave test page untouched for debugging:
    python test_scabard_api.py ... --keep
"""

import argparse
import sys
from datetime import datetime

from scabard_sdk import (
    ScabardAuthError,
    ScabardClient,
    ScabardError,
    ScabardForbiddenError,
    ScabardNotFoundError,
)

# ── Mini test harness ─────────────────────────────────────────────────────────

_results: list[tuple[str, bool, str]] = []


def run_test(name: str, fn) -> bool:
    """Run fn(), record PASS/FAIL. Returns True if passed."""
    try:
        fn()
        _results.append((name, True, ""))
        print(f"  PASS  {name}")
        return True
    except AssertionError as e:
        _results.append((name, False, str(e)))
        print(f"  FAIL  {name}: {e}")
        return False
    except Exception as e:
        _results.append((name, False, f"{type(e).__name__}: {e}"))
        print(f"  FAIL  {name}: {type(e).__name__}: {e}")
        return False


def skip(name: str, reason: str) -> None:
    _results.append((name, False, f"SKIPPED — {reason}"))
    print(f"  SKIP  {name} ({reason})")


def assert_true(label: str, value) -> None:
    if not value:
        raise AssertionError(f"{label} was falsy: {value!r}")


def assert_eq(label: str, actual, expected) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_in(label: str, item, container) -> None:
    if item not in container:
        raise AssertionError(f"{label}: {item!r} not found in result")


def assert_raises(exc_type, fn) -> None:
    try:
        fn()
    except exc_type:
        return
    raise AssertionError(f"Expected {exc_type.__name__} to be raised, but it was not")


# ── Tests ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Integration tests for the Scabard API."
    )
    parser.add_argument("--username", required=True, help="Scabard username")
    parser.add_argument("--access-key", required=True,
                        help="API access key (from your profile page; expires 24 hr)")
    parser.add_argument("--campaign-id", type=int, required=True,
                        help="Campaign ID to test against (must be one you own)")
    parser.add_argument("--concept", default="character",
                        help="Concept to use for create/update tests (default: character)")
    parser.add_argument("--keep", action="store_true",
                        help="Skip cleanup — leave test page in campaign as-is")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    test_page_name = f"TEST SDK Page {ts}"
    test_page_name_updated = f"TEST SDK Page {ts} [UPDATED]"
    test_target_page_name = f"TEST SDK Target {ts}"

    client = ScabardClient(username=args.username, access_key=args.access_key)
    bad_client = ScabardClient(username="__invalid__", access_key="00000000000000000")

    print(f"\nScabard API Integration Tests")
    print("=" * 50)
    print(f"Campaign ID : {args.campaign_id}")
    print(f"Concept     : {args.concept}")
    print(f"Username    : {args.username}")
    print()

    # Track created pages across sections — used for dependent tests and cleanup
    created_thing_id: int | None = None
    created_target_thing_id: int | None = None

    # ── Section 1: Auth errors ────────────────────────────────────────────────
    print("[1] Auth error handling")

    run_test("auth_bad_credentials_raises_ScabardAuthError", lambda: assert_raises(
        ScabardAuthError,
        lambda: bad_client.list_campaigns(),
    ))

    # ── Section 2: Campaign access ────────────────────────────────────────────
    print("\n[2] Campaign access")

    def test_list_campaigns():
        campaigns = client.list_campaigns()
        assert_true("list_campaigns() returns a list", isinstance(campaigns, list))

    def test_get_campaign():
        result = client.get_campaign(args.campaign_id)
        assert_in("get_campaign() has 'main' key", "main", result)
        assert_in("get_campaign() has 'rows' key", "rows", result)
        assert_true("main is a dict", isinstance(result["main"], dict))
        assert_true("rows is a list", isinstance(result["rows"], list))

    def test_list_pages():
        pages = client.list_pages(args.campaign_id, args.concept)
        assert_true("list_pages() returns a list", isinstance(pages, list))

    def test_invalid_campaign_raises():
        # Scabard returns 500 for unknown campaign IDs (not 404/403 as the docs
        # suggest) — accept any ScabardError as a valid "access denied" signal.
        assert_raises(
            ScabardError,
            lambda: client.get_campaign(999999999),
        )

    def test_list_connection_types():
        conn_types = client.list_connection_types(args.concept)
        assert_true("list_connection_types() returns a list", isinstance(conn_types, list))
        assert_true("list_connection_types() is non-empty", len(conn_types) > 0)
        first = conn_types[0]
        for key in ("rel", "source", "target"):
            assert_in(f"connection type entry has '{key}'", key, first)
        print(f"         ({len(conn_types)} types; sample: "
              f"{first.get('source')} —[{first.get('rel')}]→ {first.get('target')})")

    run_test("list_campaigns", test_list_campaigns)
    run_test("get_campaign", test_get_campaign)
    run_test("list_pages", test_list_pages)
    run_test("list_connection_types", test_list_connection_types)
    run_test("invalid_campaign_id_raises", test_invalid_campaign_raises)

    # ── Section 3: Page lifecycle ─────────────────────────────────────────────
    print("\n[3] Page lifecycle")

    # create_page — all subsequent tests depend on this
    def test_create_page():
        nonlocal created_thing_id
        ok, thing_id = client.create_page(
            campaign_id=args.campaign_id,
            concept=args.concept,
            name=test_page_name,
            brief_summary="Temporary test page created by test_scabard_api.py.",
            description=f"Created at {ts}. Safe to delete.",
            secrets="GM-only test secret.",
        )
        assert_true("create_page() returns True", ok)
        # If the re-fetch didn't find the ID (timing), do a manual fallback lookup
        if thing_id is None:
            existing = client.fetch_existing(args.campaign_id, args.concept)
            thing_id = existing.get(test_page_name)
        assert_true("create_page() returns a thing_id", thing_id is not None)
        created_thing_id = thing_id
        print(f"         (thing_id={thing_id})")

    create_passed = run_test("create_page", test_create_page)

    if not create_passed:
        for name in [
            "get_created_page",
            "created_page_in_list",
            "update_page",
            "get_updated_page",
            "fetch_existing_contains_page",
        ]:
            skip(name, "create_page failed")
    else:
        def test_get_created_page():
            page = client.get_page(args.campaign_id, args.concept, created_thing_id)
            assert_true("get_page() returns a dict", isinstance(page, dict))
            assert_eq("page name matches", page.get("name"), test_page_name)

        def test_created_page_in_list():
            existing = client.fetch_existing(args.campaign_id, args.concept)
            ids = list(existing.values())
            assert_in("created thing_id in list_pages()", created_thing_id, ids)

        def test_update_page():
            ok = client.update_page(
                campaign_id=args.campaign_id,
                concept=args.concept,
                thing_id=created_thing_id,
                name=test_page_name_updated,
                brief_summary="Updated by test_scabard_api.py.",
                description=f"Updated at {ts}.",
                secrets="Updated GM secret.",
            )
            assert_true("update_page() returns True", ok)

        def test_get_updated_page():
            page = client.get_page(args.campaign_id, args.concept, created_thing_id)
            assert_eq("page name reflects update", page.get("name"), test_page_name_updated)

        def test_fetch_existing():
            existing = client.fetch_existing(args.campaign_id, args.concept)
            assert_true("fetch_existing() returns a dict", isinstance(existing, dict))
            assert_in("updated page name in fetch_existing()", test_page_name_updated, existing)
            assert_eq("fetch_existing maps name to correct id",
                      existing[test_page_name_updated], created_thing_id)

        run_test("get_created_page", test_get_created_page)
        run_test("created_page_in_list", test_created_page_in_list)
        run_test("update_page", test_update_page)
        run_test("get_updated_page", test_get_updated_page)
        run_test("fetch_existing_contains_page", test_fetch_existing)

    # ── Section 4: Connection creation ────────────────────────────────────────
    print("\n[4] Connection creation")

    if created_thing_id is None:
        for name in ("create_target_page", "create_connection_between_test_pages"):
            skip(name, "source page was not created")
    else:
        def test_create_target_page():
            nonlocal created_target_thing_id
            ok, thing_id = client.create_page(
                campaign_id=args.campaign_id,
                concept=args.concept,
                name=test_target_page_name,
                brief_summary="Temporary target page for create_connections test.",
                description=f"Created at {ts}. Safe to delete.",
            )
            assert_true("create_page() returns True for target", ok)
            if thing_id is None:
                existing = client.fetch_existing(args.campaign_id, args.concept)
                thing_id = existing.get(test_target_page_name)
            assert_true("target thing_id resolved", thing_id is not None)
            created_target_thing_id = thing_id
            print(f"         (target thing_id={thing_id})")

        target_created = run_test("create_target_page", test_create_target_page)

        if not target_created:
            skip("create_connection_between_test_pages",
                 "target page creation failed")
        else:
            def test_create_connection():
                # Pick a self-referential connection type for this concept so
                # the test doesn't depend on a second concept having pages.
                conn_types = client.list_connection_types(args.concept)
                title_concept = args.concept.title()
                candidates = [
                    ct for ct in conn_types
                    if ct.get("source") == title_concept
                    and ct.get("target") == title_concept
                    and ct.get("postParam")
                ]
                if not candidates:
                    raise AssertionError(
                        f"no {title_concept}→{title_concept} connection types "
                        f"in catalog for concept '{args.concept}'"
                    )
                chosen = candidates[0]
                post_param = chosen["postParam"]
                rel_label = chosen.get("rel", "?")

                ok, records = client.create_connections(
                    campaign_id=args.campaign_id,
                    concept=args.concept,
                    thing_id=created_thing_id,
                    connections={post_param: test_target_page_name},
                )
                assert_true("create_connections() reports isSuccess=True", ok)
                assert_in("response contains chosen postParam",
                          post_param, records)
                record = records[post_param]
                assert_eq("connection target value matches",
                          record.get("value"), test_target_page_name)
                rel_id = record.get("relId")
                assert_true("relId is an int", isinstance(rel_id, int))
                uri = record.get("uri", "")
                assert_true("uri is a non-empty str",
                            isinstance(uri, str) and len(uri) > 0)
                print(f"         ({title_concept} —[{rel_label}]→ "
                      f"{title_concept}, relId={rel_id})")

            run_test("create_connection_between_test_pages",
                     test_create_connection)

    # ── Section 5: Cleanup ────────────────────────────────────────────────────
    print("\n[5] Cleanup")

    cleanup_targets: list[tuple[str, int, str]] = []
    if created_thing_id is not None:
        cleanup_targets.append(
            ("source", created_thing_id, test_page_name_updated)
        )
    if created_target_thing_id is not None:
        cleanup_targets.append(
            ("target", created_target_thing_id, test_target_page_name)
        )

    if not cleanup_targets:
        skip("cleanup_mark_test_pages", "no pages were created")
    elif args.keep:
        skip("cleanup_mark_test_pages", "--keep flag set")
        for role, tid, pname in cleanup_targets:
            print(f"         NOTE: Test {role} page left as-is "
                  f"(id={tid}, name='{pname}')")
    else:
        def test_cleanup():
            for role, tid, pname in cleanup_targets:
                ok = client.update_page(
                    campaign_id=args.campaign_id,
                    concept=args.concept,
                    thing_id=tid,
                    name=pname,
                    brief_summary="[TEST PAGE - SAFE TO DELETE]",
                    description=(
                        f"This page was created by `test_scabard_api.py` on "
                        f"{ts} as part of SDK integration testing "
                        f"({role} page).\n\n"
                        f"It is safe to delete."
                    ),
                )
                assert_true(f"cleanup update_page() for {role} returns True", ok)

        if run_test("cleanup_mark_test_pages", test_cleanup):
            for role, tid, _ in cleanup_targets:
                print(f"         NOTE: Test {role} page id={tid} marked "
                      f"'[TEST PAGE - SAFE TO DELETE]' — delete it manually "
                      f"in Scabard.")

    # ── Summary ───────────────────────────────────────────────────────────────
    passed = sum(1 for _, ok, _ in _results if ok)
    total = len(_results)
    failed = [(name, detail) for name, ok, detail in _results if not ok]

    print(f"\n{'=' * 50}")
    print(f"Results: {passed}/{total} passed")
    if failed:
        print()
        for name, detail in failed:
            print(f"  FAIL  {name}: {detail}")

    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
