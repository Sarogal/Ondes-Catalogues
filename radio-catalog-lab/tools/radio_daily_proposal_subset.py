"""Select only an exact subset of recomputed proposals; never filter source evidence."""
def select_proposals(rows, key, selected, maximum):
    if selected is None:
        if not 0 < len(rows) <= maximum:
            raise ValueError("no qualified proposal or budget exceeded")
        return rows
    allowed = {row[key] for row in rows}
    if (not isinstance(selected, (tuple,list)) or not 0 < len(selected) <= maximum
            or any(not isinstance(x,str) for x in selected)
            or len(set(selected)) != len(selected) or not set(selected) <= allowed):
        raise ValueError("invalid selected proposal subset")
    return [row for row in rows if row[key] in selected]


def isolate(pointer, raw, *, anchor, day, proposed, key, qualify, validate, evidence, live, maximum):
    # A common network budget and immutable in-process observations cover
    # the whole family, including subsequent combined validation.
    from radio_daily_live_evidence import EvidenceDeferred
    from radio_daily_v9_generator import digest
    import datetime as dt
    selected = []
    candidate = None
    verified = None
    deferred = []
    ids = sorted({row[key] for row in proposed})
    if ids:
        offset = dt.date.fromisoformat(day).toordinal() % len(ids)
        ids = ids[offset:] + ids[:offset]
    for index, identifier in enumerate(ids):
        if index >= maximum:
            deferred.append(dict(id=identifier, reason="family_attempt_budget"))
            continue
        trial = sorted(selected+[identifier])
        args = dict(evidence, **live.services(), selected=trial)
        try:
            body = qualify(pointer, raw, anchor=anchor, day=day, **args)
            sha = validate(pointer, raw, body, anchor=anchor, day=day, **args)
            if sha != digest(body):
                raise ValueError("selected candidate digest mismatch")
        except EvidenceDeferred:
            deferred.append(dict(id=identifier, reason="live_evidence_deferred"))
            continue
        except ValueError:
            deferred.append(dict(id=identifier, reason="strict_gate_held"))
            continue
        selected, candidate, verified = trial, body, sha
    result = dict(proposalCount=len(proposed), networkCalls=live.calls,
        candidateSha256=verified, selectedCount=len(selected), deferred=deferred,
        outcome="strict_gate_validated" if selected else ("strict_gate_held" if proposed else "no_proposal"))
    material = None if candidate is None else dict(candidate=candidate,
        evidence=dict(evidence, **live.services(), selected=selected))
    return result, material
