# Radio publisher activation contract (not activated)

The current daily workflow is preview-only and pinned to authenticated TEST v8.
This document does not authorize changes to that workflow, the TEST pointer,
production, or PR #474. The local Git transfer is synthetic and has no network
or secret access.

## Proposed isolated jobs

1. Discovery, verification and unsigned proposal: contents read, no signing
   secret, no write token, no credentials persisted in checkout. Reject a
   proposal that does not reproduce exact authorized deltas.
2. Signing: a separate trusted job from reviewed code only, with a protected
   environment and no untrusted checkout, pull request input or shell
   interpolation. Revalidate evidence, predecessor and candidate bytes before
   signing. Pin the public key independently of the proposed pointer.
3. Transport: no signing key; receives only the signed public snapshot. Use a
   separately scoped writer identity for the explicitly authorized catalogue
   destination. Check exact repository/ref, ancestor and expected remote SHA.
   Use a single Git commit and an explicit lease; refuse non-fast-forward
   replacement even when a lease would allow it.
4. Readback: read-only independent verification at an exact deployed revision.
   Git ref success is not proof of Pages deployment or public availability.
   Verify pointer, catalogue, every referenced image and public endpoint after
   deployment before recording successful publication.

## Secrets and authorization

No actual secret is provisioned by this change. For an eventual protected
environment, choose a separate signing key and a separately scoped short-lived
writer credential. Keep private signing material and decryption credentials
out of Git, logs, artifacts, caches and public state. Use the runner's private
temporary directory, restrictive permissions and cleanup. Never expose the
signing credential to discovery jobs or the Git credential to signing jobs.
Prefer environment protection, trusted workflow code, restricted triggers and
a rotation/revocation plan. A key change requires explicit trust migration;
do not assume the existing Android TEST public key can verify a different key.

Do not add a write-capable scheduled job or switch the pinned TEST v8 context
until separately authorized. A protected environment requiring approval is
appropriate for activation; decide the unattended policy only after the
reviewed security gates and test publication have been accepted.

## Dormant role configuration

The role adapter `tools/radio_daily_publisher_job_config.py` accepts only
explicit role-specific mappings. It rejects cross-role secrets, unexpected
repository ID, ref, reviewed commit, event, and environment. Its initial
execution contract permits only reviewed manual laboratory dispatches; it
does not enable that dispatch or create environments.

| Role | Proposed protected environment | Explicit credential inputs |
| --- | --- | --- |
| Collector | none | none |
| Signer | radio-lab-signing | RADIO_LAB_ENCRYPTED_KEY, RADIO_LAB_PASSPHRASE |
| Publisher | radio-lab-transport | RADIO_LAB_WRITE_TOKEN |
| Readback | radio-lab-readback | RADIO_LAB_READ_TOKEN |

The public pin is independent, nonsecret configuration. Signing rejects the
TEST key. Transport requires explicit authorization and the fixed laboratory
ref. Readback receives no writer credential. In-process callbacks for
pre/post-transfer verification are not proof of job isolation; the eventual
trusted orchestration must independently enforce runner, environment, token
scope and checkout restrictions. Do not expose real secrets to PR workflows.
No protected environments, tokens or remote branches are created by this code.

## Remaining proof

Local push tests do not establish GitHub permissions, branch protection,
actual secret availability, Pages consistency or Android compatibility with a
new trust anchor. Runs 253 and 254 qualified real discovered stations and
rehearsed publication locally; neither published a signed catalogue remotely. The exact destination URL,
branch and public key must be approved before an actual remote adapter is
connected. A failed deployment must retain the previous verified release;
a retry must not allocate another sequence for the same signed bytes.

## Remote acceptance and state transition

`tools/radio_daily_remote_acceptance.py::prepare_remote` connects the
independent Git history and HTTPS deployment acceptance to the existing
release context/migration contract. It consumes the same verified snapshot,
requires complete predecessor evidence for an advancing release, and rechecks
the Git head before returning. It does not persist state or activate a job.
An unchanged accepted release does not allocate another sequence.

Before any rehearsal using actual credentials:

- The proposed isolated rehearsal endpoint is now
  `https://raw.githubusercontent.com/Sarogal/Ondes-Catalogues/refs/heads/radio-lab-publisher-rehearsal/`.
  No production Pages settings are changed. The branch must be created by the
  exact signed sequence-8 root transfer, never from main or the code branch.
  GitHub Raw is only the rehearsal distribution endpoint, not a production
  hosting decision. No signed bytes may be rewritten after signing.
- A trusted deployment job must record the actual isolated ref/commit in
  GitHub Deployments and independently verify the public pointer, body and
  artwork. Raw CDN propagation can lag; retry the same commit and sequence.
  A Git push or a successful deployment record alone is not acceptance.
- Wire trusted manual jobs to transfer exact public snapshot material, verify
  the accepted deployment and atomically persist migrated evidence against the
  retained predecessor. Retain the previous accepted context on any failure.
- Approve the independent public key pin and protected role environments.
  No private key or write credential is provisioned here.

A real rehearsal, then a separately authorized trust transition to Android,
are required before unattended publication can be enabled.

## Owner-authorized first real isolated release

The owner explicitly authorized the protected environments, experimental key,
isolated ref writes and first signed remote catalogue on 2026-11-27. This
does not authorize production, Android changes or merging PR #474.

The one-time owner workstation command
`python radio_lab_provision.py --activate-isolated-lab` creates the three
branch-restricted environments, requires owner approval on the signing
environment, generates an encrypted Ed25519 key and installs it through
GitHub CLI stdin. The public pin is stored independently in repository
variables. No secret is printed or written to Git. Setup refuses rotation
and partial identities. The experimental private key has no local backup.
No personal access token is provisioned: the transport and readback jobs
receive separate short-lived GitHub job tokens with respective permissions.

After reviewing the exact code SHA and a same-day successful discovery run,
`python radio_lab_provision.py --launch REVIEWED_SHA RUN_ID` creates a single
activation marker. A push to that marker triggers
`.github/workflows/radio-lab-first-release.yml` only on the laboratory code
branch. The first release requalifies real admissions, reanchors exact TEST
v8 bytes with the independent lab key (without changing TEST), signs V9,
exports only public bytes, transfers the root and direct successor with
explicit leases, independently verifies the actual Git ref and GitHub Raw
catalogue and artwork mirrors, and records a deployment after acceptance.
No other operation families or scheduled publication are activated yet.
Original legacy logo URLs are not rewritten or asserted to be reachable:
the independent Raw acceptance verifies the published content-addressed
copies, not the external source URLs. Android trust and URL compatibility
remain separate acceptance gates.

The new workflow is dormant until the owner creates the marker and approves
the signing environment. Its actual remote execution has not yet been
verified. On interruption after transfer, rerun only the failed job using
the existing public artifact; do not regenerate a different V9.
