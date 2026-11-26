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

## Remaining proof

Local push tests do not establish GitHub permissions, branch protection,
actual secret availability, Pages consistency, Android compatibility with a
new trust anchor, or a real admitted station. The exact destination URL,
branch and public key must be approved before an actual remote adapter is
connected. A failed deployment must retain the previous verified release;
a retry must not allocate another sequence for the same signed bytes.
