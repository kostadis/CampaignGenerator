"""CLI handlers for the safe authority foundation commands."""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import yaml

from campaignlib.config import ConfigLocationError, campaign_root_for_config, find_default_config
from campaignlib.planning_config import PlanningNoteSelector, load_planning_config
from pipelines.summary_native.authority import (AuthorityError, AuthorityLedger, DOCUMENT_ANCHOR,
                                                NoteRecord, RulingRecord, _NoDuplicatesLoader,
                                                detect_conflicts, dismiss_conflict, ledger_bytes, ledger_digest,
                                                ledger_path, load_ledger, new_ledger,
                                                record_human_conflict, resolve_conflict, sha256_bytes,
                                                validate_record_identity)
from pipelines.summary_native.authority_apply import _write_ledger_event, apply_proposal, authority_dir, authority_lock, create_proposal, initialize_ledger, pending_transaction, recover_transaction, request_withdrawal, validate_ledger_tip
from pipelines.summary_native.authority_inputs import resolve_anchor_span, resolve_selection, selected_planning_records

EXIT_BY_CODE = {"AUTH_VALIDATION": 2, "AUTH_STALE": 3, "AUTH_RECOVERY": 4, "AUTH_CONFLICT": 5}


def _stale_projections(campaign_dir: Path, current_ledger_sha256: str) -> list[dict[str, str]]:
    """Find derived runs whose recorded authority ledger is no longer current.

    This reads run metadata only.  It never opens the draft prose, so status
    cannot accidentally surface a player-only or GM-only sentence.
    """
    stale: list[dict[str, str]] = []
    for record_path in sorted(Path(campaign_dir).glob("**/state/**/runs/*/record.json")):
        try:
            run = json.loads(record_path.read_text(encoding="utf-8"))
            manifest = (run.get("inputs") or {}).get("authority_manifest")
            if not isinstance(manifest, dict) or manifest.get("ledger_sha256") == current_ledger_sha256:
                continue
            doc = str(run.get("doc") or "unknown")
            stale.append({
                "doc": doc,
                "draft": str(record_path.parent.parent / "drafts" / f"{doc}.draft.md"),
                "reason": "authority inputs changed since this output",
            })
        except (OSError, ValueError, TypeError):
            # An unreadable historical run is never silently treated current.
            stale.append({"doc": "unknown", "draft": str(record_path),
                          "reason": "authority freshness could not be verified"})
    return stale


def _emit(args, *, ok: bool, code: str, message: str, data: dict | None = None, artifacts: list[str] | None = None) -> int:
    payload = {"ok": ok, "code": code, "message": message, "artifacts": artifacts or [], "data": data or {}}
    if args.json:
        print(json.dumps(payload, sort_keys=True))
    elif ok:
        print(message)
    else:
        print(f"Error: {message}", file=sys.stderr)
    return 0 if ok else EXIT_BY_CODE.get(code, 2)


def _validated_ledger_update(ledger: AuthorityLedger, *, records: list, revision: int | None = None) -> AuthorityLedger:
    """Build a mutation through the complete ledger schema before journaling it.

    ``model_copy`` deliberately does not rerun Pydantic validation.  Authority
    mutations must never use it as a way around a record's state-machine
    requirements, so every CLI-only update takes this round trip first.
    """
    raw = ledger.model_dump(mode="json", exclude_none=True)
    raw["revision"] = ledger.revision + 1 if revision is None else revision
    raw["records"] = [record.model_dump(mode="json", exclude_none=True) for record in records]
    try:
        return AuthorityLedger.model_validate(raw)
    except Exception as exc:
        raise AuthorityError(f"AUTH_VALIDATION: invalid authority record transition: {exc}", "AUTH_VALIDATION") from exc


def _validate_note_content_digest(campaign_dir: Path, record: NoteRecord) -> None:
    """Bind a staged note revision to the bytes it currently describes."""
    source = Path(record.source.path)
    source = source if source.is_absolute() else campaign_dir / source
    try:
        data = source.read_bytes()
        content = data if record.source.anchor == DOCUMENT_ANCHOR else resolve_anchor_span(data, record.source.anchor)
    except (OSError, AuthorityError) as exc:
        raise AuthorityError("note record source is missing, unreadable, or lacks its declared anchor") from exc
    if record.content_digest != sha256_bytes(content):
        scope = "whole-file" if record.source.anchor == DOCUMENT_ANCHOR else "declared-anchor"
        raise AuthorityError(f"note record content_digest must equal the current {scope} SHA-256")


def _allow_record_revision(current, revised) -> None:
    """Allow replacement only for the next reviewed revision of an editable state."""
    if type(current) is not type(revised):
        raise AuthorityError("AUTH_VALIDATION: a record revision cannot change record kind", "AUTH_VALIDATION")
    if revised.revision != current.revision + 1:
        raise AuthorityError("AUTH_STALE: revised record must use exactly the next record revision", "AUTH_STALE")
    if isinstance(current, NoteRecord):
        if current.status != "active" or revised.status != "active":
            raise AuthorityError("AUTH_VALIDATION: only an active note can be revised", "AUTH_VALIDATION")
    elif current.status not in {"draft", "proposed"} or revised.status != "draft":
        raise AuthorityError("AUTH_VALIDATION: only a draft or proposed ruling can be revised before approval", "AUTH_VALIDATION")
    elif revised.proposal_id or revised.applied_receipt:
        raise AuthorityError("AUTH_VALIDATION: a revised draft ruling must clear its prior proposal binding", "AUTH_VALIDATION")


def load_staged_yaml(path: Path) -> object:
    """Read a staged authority document without accepting duplicate YAML keys."""
    try:
        return yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_NoDuplicatesLoader)
    except (OSError, yaml.YAMLError) as exc:
        raise AuthorityError(f"invalid staged authority YAML {path}: {exc}") from exc


def _events_for(campaign_dir: Path, *, record_id: str | None = None, conflict_id: str | None = None) -> list[dict]:
    """Read event references structurally, never by substring matching JSON text."""
    fields = {"record_id", "ruling_id"} if record_id is not None else {"conflict_id"}
    wanted = record_id if record_id is not None else conflict_id
    events: list[dict] = []
    for path in sorted((authority_dir(campaign_dir) / "events").glob("*.json")):
        try:
            event = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(event, dict) and any(event.get(field) == wanted for field in fields):
            events.append(event)
    return events


def _conflict_data(ledger: AuthorityLedger, conflict) -> dict:
    """Attach GM-visible compared-record facts without inventing a verdict."""
    data = conflict.model_dump(mode="json", exclude_none=True)
    by_id = {record.id: record for record in ledger.records}
    data["records"] = [
        {
            "id": record.id, "source": record.source.path, "anchor": record.source.anchor,
            "normalized_value": record.normalized_value,
            "effective": record.effective.model_dump(mode="json", exclude_none=True),
            "projections": sorted(projection.value for projection in record.projections),
        }
        for record_id in sorted(conflict.record_ids)
        if (record := by_id.get(record_id)) is not None
    ]
    return data


def run(args) -> int:
    try:
        campaign_dir, config_path = _resolve_campaign_scope(args)
        # Keep the resolved campaign available to shared helpers and to callers
        # that still inspect the parsed namespace.
        args.campaign_dir = str(campaign_dir)
        if args.authority_command == "notes":
            if args.authority_notes_command != "preview":
                raise AuthorityError("unsupported authority notes command")
            if args.selector:
                selectors = []
                for raw in args.selector:
                    if "=" not in raw:
                        raise AuthorityError("selector must use ID=PATH")
                    selector_id, path = raw.split("=", 1)
                    selectors.append(PlanningNoteSelector(id=selector_id, path=path))
            else:
                config = Path(args.planning_config) if args.planning_config else campaign_dir / "config" / "planning.yaml"
                try:
                    selectors = load_planning_config(config).notes
                except ValueError as exc:
                    raise AuthorityError(f"cannot read planning selectors: {exc}") from exc
                if selectors is None:
                    raise AuthorityError("planning has no configured authority notes")
            try:
                selection = resolve_selection(campaign_dir, selectors)
            except AuthorityError:
                if args.audience != "gm":
                    raise AuthorityError("selected planning authority has no complete support for this audience") from None
                raise
            if args.audience == "gm":
                ledger = load_ledger(campaign_dir, required=False)
                selected = ([] if ledger is None else
                            selected_planning_records(campaign_dir, ledger, selection, audience="gm"))
                by_path: dict[str, list] = {}
                for record in selected:
                    source = Path(record.source.path)
                    source = source if source.is_absolute() else campaign_dir / source
                    section = resolve_anchor_span(source.read_bytes(), record.source.anchor)
                    by_path.setdefault(str(source.resolve()), []).append({
                        "id": record.id, "classification": record.classification.value,
                        "audience": sorted(record.audience.grants),
                        "effective": record.effective.model_dump(mode="json", exclude_none=True),
                        "status": record.status, "anchor": record.source.anchor,
                        "section_sha256": sha256_bytes(section),
                    })
                members = [
                    {"selector_id": member.selector_id, "path": member.authored_path,
                     "resolved_path": member.resolved_path, "external": member.external,
                     "record_ids": list(member.record_ids), "reason": member.reason,
                     "sha256": member.digest,
                     "records": sorted(by_path.get(member.resolved_path, []), key=lambda item: item["id"])}
                    for member in selection.members
                ]
            else:
                try:
                    ledger = load_ledger(campaign_dir)
                    selected_planning_records(campaign_dir, ledger, selection, audience=args.audience)
                except AuthorityError:
                    raise AuthorityError("selected planning authority has no complete support for this audience") from None
                # Never disclose selector locations, external markers, or
                # record identities in a non-GM preview.
                members = [{"authorized": True, "reason": "selected support"} for _ in selection.members]
            return _emit(args, ok=True, code="OK", message="authority note selection preview",
                         data={"audience": args.audience, "members": members,
                               "selection_sha256": selection.digest,
                               "selection_digest": selection.digest,
                               "selectors_sha256": selection.selectors_digest,
                               "membership_digest": selection.membership_digest,
                               "warnings": ["external selection" for member in members if member.get("external")] if args.audience == "gm" else []})
        if args.authority_command == "record":
            stages = authority_dir(campaign_dir) / "stages"
            if args.record_command == "stage":
                raw = load_staged_yaml(Path(args.record_file))
                kind = raw.get("kind") if isinstance(raw, dict) else None
                model = RulingRecord if kind == "ruling" else NoteRecord if kind == "note" else None
                if model is None: raise AuthorityError("record stage requires one strict ruling or note mapping")
                record = model.model_validate(raw)
                if isinstance(record, NoteRecord):
                    _validate_note_content_digest(campaign_dir, record)
                stage_id = f"stage-{uuid.uuid4().hex}"
                payload = {"id": stage_id, "record": record.model_dump(mode="json", exclude_none=True)}
                payload["sha256"] = sha256_bytes(json.dumps(payload, sort_keys=True).encode())
                path = stages / f"{stage_id}.json"; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n")
                return _emit(args, ok=True, code="OK", message="record staged for explicit apply", data=payload, artifacts=[str(path)])
            with authority_lock(campaign_dir, exclusive=True):
                ledger = load_ledger(campaign_dir)
                # Validate the complete loaded authority graph before creating
                # a journal whose snapshots would otherwise bless invalid data.
                ledger = _validated_ledger_update(ledger, records=ledger.records, revision=ledger.revision)
                if args.expected_ledger_sha256 != ledger_digest(campaign_dir): raise AuthorityError("AUTH_STALE: ledger changed since review", "AUTH_STALE")
                if args.record_command == "apply":
                    payload = json.loads((stages / f"{args.stage_id}.json").read_text())
                    if payload.get("sha256") != args.stage_sha256: raise AuthorityError("AUTH_STALE: staged record digest changed", "AUTH_STALE")
                    raw = payload["record"]; model = RulingRecord if raw.get("kind") == "ruling" else NoteRecord
                    record = model.model_validate(raw)
                    if isinstance(record, NoteRecord):
                        _validate_note_content_digest(campaign_dir, record)
                    validate_record_identity(campaign_dir, record)
                    existing = next((item for item in ledger.records if item.id == record.id), None)
                    if existing is not None:
                        _allow_record_revision(existing, record)
                        records = [record if item.id == record.id else item for item in ledger.records]
                        reason = "record-revise"
                    else:
                        records = [*ledger.records, record]
                        reason = "record-apply"
                    before = ledger_path(campaign_dir).read_bytes()
                    updated = _validated_ledger_update(ledger, records=records)
                    _write_ledger_event(campaign_dir, before=before, after=ledger_bytes(updated), actor=record.recorded_by, reason=reason, record_id=record.id)
                    return _emit(args, ok=True, code="OK", message="staged record applied", data={"id": record.id, "revision": record.revision, "ledger_revision": updated.revision})
                record = next((item for item in ledger.records if item.id == args.id), None)
                if record is None or record.revision != args.expected_revision: raise AuthorityError("AUTH_STALE: record revision changed", "AUTH_STALE")
                if isinstance(record, NoteRecord):
                    if record.status != "active":
                        raise AuthorityError("AUTH_VALIDATION: only an active note can be retired", "AUTH_VALIDATION")
                    status = "retired"
                else:
                    if record.status != "applied":
                        raise AuthorityError("AUTH_VALIDATION: only an applied ruling can be superseded; use the proposal or withdrawal workflow", "AUTH_VALIDATION")
                    status = "superseded"
                retired = record.model_copy(update={"status": status, "revision": record.revision + 1})
                before = ledger_path(campaign_dir).read_bytes()
                updated = _validated_ledger_update(ledger, records=[retired if item.id == record.id else item for item in ledger.records])
                _write_ledger_event(campaign_dir, before=before, after=ledger_bytes(updated), actor=record.recorded_by, reason="record-retire", record_id=record.id)
                return _emit(args, ok=True, code="OK", message="record retired", data={"id": record.id, "reason": args.reason})
        if args.authority_command == "init":
            campaign = args.campaign or campaign_dir.name
            with authority_lock(campaign_dir, exclusive=True):
                ledger = new_ledger(campaign)
                digest = initialize_ledger(campaign_dir, ledger, actor=os.environ.get("USER") or "GM", _already_locked=True)
            return _emit(args, ok=True, code="OK", message="authority ledger initialized", data={"campaign": campaign, "revision": 1, "sha256": digest}, artifacts=[str(ledger_path(campaign_dir))])
        if args.authority_command == "conflict" and args.authority_conflict_command in {"resolve", "dismiss", "identify"}:
            with authority_lock(campaign_dir, exclusive=True):
                ledger = load_ledger(campaign_dir)
                if args.expected_ledger_sha256 != ledger_digest(campaign_dir):
                    raise AuthorityError("AUTH_STALE: ledger changed since review", "AUTH_STALE")
                if args.authority_conflict_command == "resolve":
                    raw = load_staged_yaml(Path(args.resolution_record))
                    try:
                        submitted = RulingRecord.model_validate(raw)
                    except Exception as exc:
                        raise AuthorityError("conflict resolution record must be one strict ruling mapping") from exc
                    resolution = next((record for record in ledger.records if record.id == submitted.id), None)
                    if not isinstance(resolution, RulingRecord) or resolution.status != "applied":
                        raise AuthorityError("resolution record must name an applied ruling already in this ledger")
                    if resolution.model_dump(mode="json", exclude_none=True) != submitted.model_dump(mode="json", exclude_none=True):
                        raise AuthorityError("AUTH_STALE: resolution record file differs from the applied ledger record", "AUTH_STALE")
                    updated = resolve_conflict(ledger, args.id, resolution_record=resolution.id,
                                               expected_revision=ledger.revision)
                    record_id = resolution.id
                    event_reason = "conflict-resolve"
                elif args.authority_conflict_command == "dismiss":
                    updated = dismiss_conflict(ledger, args.id, expected_revision=ledger.revision)
                    record_id = None
                    event_reason = f"conflict-dismiss: {args.reason}"
                else:
                    updated = record_human_conflict(ledger, conflict_id=args.id,
                                                    record_ids=set(args.record_ids), basis=args.basis)
                    record_id = None
                    event_reason = f"conflict-identify: {args.reason}"
                before = ledger_path(campaign_dir).read_bytes()
                _write_ledger_event(campaign_dir, before=before, after=ledger_bytes(updated),
                                    actor=os.environ.get("USER") or "GM", reason=event_reason,
                                    record_id=record_id, conflict_id=args.id)
                changed = next(conflict for conflict in updated.conflicts if conflict.id == args.id)
                verb = {"resolve": "resolved", "dismiss": "dismissed", "identify": "recorded"}[args.authority_conflict_command]
                return _emit(args, ok=True, code="OK", message=f"authority conflict {verb}",
                             data={"conflict": _conflict_data(updated, changed),
                                   "ledger_revision": updated.revision,
                                   "ledger_sha256": sha256_bytes(ledger_bytes(updated))})
        with authority_lock(campaign_dir, exclusive=False):
            pending = pending_transaction(campaign_dir)
            exists = ledger_path(campaign_dir).is_file()
            if args.authority_command == "status":
                if not exists:
                    return _emit(
                        args, ok=True, code="OK", message="authority is absent",
                        data={"state": "absent", "campaign": None, "revision": None,
                              "sha256": None, "records": 0, "conflicts": 0,
                              "pending_transaction": pending.get("id") if pending else None,
                              "stale_projections": []},
                    )
                ledger = load_ledger(campaign_dir)
                digest = ledger_digest(campaign_dir)
                return _emit(
                    args, ok=True, code="OK", message="authority status",
                    data={"state": "pending" if pending else "initialized", "campaign": ledger.campaign,
                          "revision": ledger.revision, "sha256": digest, "records": len(ledger.records),
                          "conflicts": len(detect_conflicts(ledger)),
                          "pending_transaction": pending.get("id") if pending else None,
                          "stale_projections": _stale_projections(campaign_dir, digest)},
                )
            if pending:
                identifier = pending.get("id", "unknown")
                raise AuthorityError(
                    f"AUTH_PENDING_TRANSACTION: recover with `summary_native authority recover {identifier}`",
                    "AUTH_RECOVERY",
                )
            ledger = load_ledger(campaign_dir)
            for record in ledger.records:
                validate_record_identity(campaign_dir, record)
            digest = ledger_digest(campaign_dir)
            if args.authority_command == "validate":
                validate_ledger_tip(campaign_dir)
        if args.authority_command == "validate":
            conflicts = [conflict for conflict in detect_conflicts(ledger) if conflict.status == "open"]
            if conflicts:
                return _emit(args, ok=False, code="AUTH_CONFLICT", message="authority ledger has unresolved conflicts",
                             data={"conflicts": [conflict.model_dump(mode="json", exclude_none=True) for conflict in conflicts]})
            return _emit(args, ok=True, code="OK", message="authority ledger is valid", data={"campaign": ledger.campaign, "revision": ledger.revision, "sha256": digest})
        if args.authority_command == "list":
            records = [record.model_dump(mode="json", exclude_none=True) for record in ledger.records if not args.status or record.status == args.status]
            return _emit(args, ok=True, code="OK", message="authority records", data={"records": records})
        if args.authority_command == "conflicts":
            conflicts = [_conflict_data(ledger, conflict) for conflict in detect_conflicts(ledger)
                         if not args.status or conflict.status == args.status]
            return _emit(args, ok=True, code="OK", message="authority conflicts", data={"conflicts": conflicts})
        if args.authority_command in {"show", "history"}:
            record = next((record for record in ledger.records if record.id == args.id), None)
            if record is None: raise AuthorityError(f"unknown authority record {args.id!r}")
            if args.authority_command == "show": return _emit(args, ok=True, code="OK", message="authority record", data={"record": record.model_dump(mode="json", exclude_none=True)})
            history = _events_for(campaign_dir, record_id=args.id)
            return _emit(args, ok=True, code="OK", message="authority history", data={"record": record.model_dump(mode="json", exclude_none=True), "events": history})
        if args.authority_command == "conflict" and args.authority_conflict_command == "history":
            conflict = next((finding for finding in detect_conflicts(ledger) if finding.id == args.id), None)
            if conflict is None:
                raise AuthorityError(f"unknown authority conflict {args.id!r}")
            return _emit(args, ok=True, code="OK", message="authority conflict history",
                         data={"conflict": _conflict_data(ledger, conflict),
                               "events": _events_for(campaign_dir, conflict_id=args.id)})
        if args.authority_command == "propose":
            proposal = create_proposal(campaign_dir, args.id, summaries_dir=_summaries_dir(args, campaign_dir, config_path))
            return _emit(args, ok=True, code="OK", message="proposal staged for review", data=proposal, artifacts=[str(authority_dir(campaign_dir) / "proposals" / proposal["id"] / "proposal.json")])
        if args.authority_command == "apply":
            receipt = apply_proposal(campaign_dir, args.id, proposal_sha256=args.proposal_sha256, actor=os.environ.get("USER") or "GM")
            return _emit(args, ok=True, code="OK", message="proposal applied", data=receipt)
        if args.authority_command == "recover":
            journal = recover_transaction(campaign_dir, args.id)
            return _emit(args, ok=True, code="OK", message="transaction recovered", data=journal)
        if args.authority_command == "withdraw":
            proposal = request_withdrawal(campaign_dir, ruling_id=args.id, reason=args.reason)
            return _emit(args, ok=True, code="OK", message="withdrawal proposal created for review", data=proposal,
                         artifacts=[str(authority_dir(campaign_dir) / "proposals" / proposal["id"] / "proposal.json")])
        raise AuthorityError(f"unsupported authority foundation command {args.authority_command!r}")
    except AuthorityError as exc:
        return _emit(args, ok=False, code=exc.code, message=str(exc))


def _resolve_campaign_scope(args) -> tuple[Path, Path | None]:
    """Resolve one authority campaign from an explicit dir or a campaign config.

    ``--campaign-dir`` remains the concise operational spelling.  ``--config``
    is the normal Summary Native workflow and is intentionally accepted by all
    authority commands so a command cannot silently use a different campaign.
    """
    if getattr(args, "campaign_dir", None):
        campaign_dir = Path(args.campaign_dir).expanduser().resolve()
        config_arg = getattr(args, "config", None)
        if not config_arg:
            return campaign_dir, None
        config_path = Path(config_arg).expanduser().resolve()
        try:
            config_root = campaign_root_for_config(config_path)
        except ConfigLocationError as exc:
            raise AuthorityError(str(exc)) from exc
        if config_root.resolve() != campaign_dir:
            raise AuthorityError("--config and --campaign-dir name different campaigns")
        return campaign_dir, config_path
    try:
        config_path = Path(getattr(args, "config", None) or find_default_config()).expanduser().resolve()
        return campaign_root_for_config(config_path), config_path
    except ConfigLocationError as exc:
        raise AuthorityError(str(exc)) from exc


def _summaries_dir(args, campaign_dir: Path, config_path: Path | None) -> Path:
    """``--summaries-dir`` > configured Summary Native directory > campaign default."""
    if args.summaries_dir:
        value = args.summaries_dir
    else:
        cfg_path = config_path or campaign_dir / "config" / "config.yaml"
        grounding = cfg_path.parent / "grounding.yaml"
        value = None
        if grounding.is_file():
            try:
                raw = yaml.safe_load(grounding.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                raise AuthorityError(f"cannot read Summary Native configuration: {exc}") from exc
            section = raw.get("summary_native") if isinstance(raw, dict) else None
            value = section.get("summaries_dir") if isinstance(section, dict) else None
        value = value or "docs/summaries"
    path = Path(value).expanduser()
    return path if path.is_absolute() else campaign_dir / path
