from pipelines.summary_native.notes import cache_key


def test_authority_cache_identity_rejects_cross_audience_and_revision_reuse():
    common = dict(system="system", user="authorized", backend="dgx", model="model", max_tokens=1, chunk_chars=1,
                  authority_policy_version=1, authority_records_digest="records-v1", source_digest="source-v1",
                  selection_membership_digest="selection-v1")
    player = cache_key(**common, audience="players", filtered_payload_digest="player-bytes")
    assert player != cache_key(**common, audience="character:ara", filtered_payload_digest="player-bytes")
    assert player != cache_key(**common, audience="players", filtered_payload_digest="ara-bytes")
    assert player != cache_key(**{**common, "authority_policy_version": 2}, audience="players", filtered_payload_digest="player-bytes")
    assert player != cache_key(**{**common, "authority_records_digest": "records-v2"}, audience="players", filtered_payload_digest="player-bytes")
    assert player != cache_key(**{**common, "source_digest": "source-v2"}, audience="players", filtered_payload_digest="player-bytes")
