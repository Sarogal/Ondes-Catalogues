#!/usr/bin/env python3
"""Croisement de tournées officielles sans fusion automatique des concerts.

Deux artistes annonçant une même date dans une même salle peuvent jouer une
affiche commune OU deux manifestations distinctes. Conserver séparément les
preuves et les identifiants ; signaler le rapprochement en revue privée.
"""
from __future__ import annotations

from collections import defaultdict

import discover
import livenation_tour_adapter


def grouping_key(row):
    date = row.get("date")
    if not isinstance(date, str) or not discover.iso_day(date) == date:
        return None
    venue_id = row.get("venueIdIfKnown")
    venue = discover.norm(row.get("venue"))
    city = ((row.get("venueReconciliation") or {}).get("canonicalCity")
            or row.get("city"))
    normalized_city = livenation_tour_adapter.normalized_city(city)
    if not normalized_city:
        return None
    if venue_id:
        return date, normalized_city, "id:" + str(venue_id)
    if not venue:
        return None
    return date, normalized_city, "name:" + venue


def annotate(candidates):
    """Marque les collisions inter-artistes, sans effacer ou combiner les pistes."""
    groups = defaultdict(list)
    for row in candidates:
        if (row.get("publicationAllowed") is not False
                or row.get("reviewRequired") is not True):
            raise ValueError("Toute piste croisée doit déjà être mise en quarantaine")
        key = grouping_key(row)
        if key and row.get("artistId") and row.get("candidateId"):
            groups[key].append(row)
    overlapping = {}
    for records in groups.values():
        artists = {row["artistId"] for row in records}
        if len(artists) < 2:
            continue
        ids = {r["candidateId"] for r in records}
        if len(ids) != len(records):
            raise ValueError("ID de candidat répété dans un groupe")
        for record in records:
            overlapping[record["candidateId"]] = {
                "otherArtistIds": sorted(artists - {record["artistId"]}),
                "otherCandidateIds": sorted(ids - {record["candidateId"]}),
                "status": "potential_shared_bill_review_only",
                "lineupConfirmed": False,
            }
    output = []
    for candidate in candidates:
        row = dict(candidate)
        if candidate.get("candidateId") in overlapping:
            row["crossArtistTourReview"] = overlapping[candidate["candidateId"]]
            row["lineupToConfirm"] = True
            row["publicationAllowed"] = False
            row["reviewRequired"] = True
        output.append(row)
    return output, len(set(
        grouping_key(x) for x in output
        if "crossArtistTourReview" in x
    ))
