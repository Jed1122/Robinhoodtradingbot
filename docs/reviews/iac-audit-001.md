# IAC-AUDIT-001: static infrastructure drift and recovery audit

**Audit date:** 2026-09-14

**Repository revision:** `a58f6ebd548d8a9368c1dc90b6a98b48ee0e5908`

**Scope:** documentation-only comparison of repository infrastructure and recovery
assumptions with the sanitized operator snapshot supplied for this audit.

## Scope, evidence, and disposition

This audit made no network request, inspected no credentials, account data, production
ledger, host, cloud API, or Terraform state, and performed no infrastructure mutation.
The supplied snapshot says only that a manually created DigitalOcean Ubuntu 24.04,
2 GB, x86_64 Droplet has an older paused container that is running and healthy with
zero host mounts; the newly committed attestation code is not deployed; and a local
image for this revision was built for arm64. It makes no assertion about uninspected
host state.

The affected deployment/IaC subsystem is **partial and externally unverified**. The
repository has fail-closed deployment controls and recovery utilities, but its
Terraform/cloud-init path is explicitly not an independently validated bootstrap path
(`docs/operations-runbook.md:29-37`), and the snapshot supplies too little host evidence
to establish conformance. The current production promotion disposition remains
**NO-GO**. This report is **READY_FOR_INTEGRATION as a static audit only**; it is not
deployment approval, recovery evidence, or a release-safety decision.

Frozen by this audit: deployment paths, firewall policy, the root-owned attestation and
rollback model, live-disabled defaults, and every production code/configuration
interface. No profitability claim is made.

## Repository baseline

- Terraform declares one managed Droplet with monitoring enabled
  (`infra/digitalocean/main.tf:1`), a provider pinned to 2.95.0
  (`infra/digitalocean/versions.tf:1`), a default `s-1vcpu-1gb` size and a required
  reviewed `ubuntu-26-04-x64` slug (`infra/digitalocean/variables.tf:4-6`). The resource
  actually consumes `droplet_image_id`, not `droplet_image_slug`; therefore slug
  validation does not prove the selected image ID has that OS or architecture.
- The declared cloud firewall permits inbound TCP/22 only from
  `trusted_ssh_cidrs`, and outbound TCP/443 plus UDP/53 and UDP/123
  (`infra/digitalocean/firewall.tf:1-6`). No repository evidence links that firewall to
  the manually created host.
- Cloud-init creates UID/GID 10001, disables root/password SSH, and creates/chowns
  state, log, configuration, and backup paths (`infra/digitalocean/cloud-init.yaml.tftpl:3-18`).
  It does not install Docker, Compose, the deployment helper, Compose content, host
  firewall tooling, swap, or backup scheduling; the runbook assigns those steps to a
  manual administrator (`docs/operations-runbook.md:12-27`).
- The default image runs as UID/GID 10001, keeps both live flags false, and starts the
  paused health service (`Dockerfile:16-26`). Default Compose has a read-only filesystem,
  drops all capabilities, binds monitoring only to host loopback, sets both live flags
  false, and declares no volumes (`docker-compose.yml:2-21`). Thus zero mounts is
  consistent with the *default paused profile*, not evidence that the deployed Compose,
  image, or host is current.
- The root deployment helper pins the exact Compose hash, rejects unsafe ownership,
  compares exact image/config identities, tests health, readiness denial, and the
  live-disabled metric, then writes a root-owned mode-0444 attestation before advancing
  `last-good` (`infra/digitalocean/deploy-remote.sh:14-21`,
  `infra/digitalocean/deploy-remote.sh:90-131`,
  `infra/digitalocean/deploy-remote.sh:301-306`). Rollback restores the prior Compose and
  environment and re-verifies that paused service (`infra/digitalocean/deploy-remote.sh:223-258`).

## Prioritized findings

### Critical blockers

1. **Confirmed release/platform mismatch — Critical.** The only image reported for
   revision `a58f6eb` is arm64, while the host is x86_64/amd64. It is not a deployable
   candidate for that host. A trusted native amd64 build (or explicitly reviewed amd64
   build pipeline) must produce an immutable local image ID; `make build` does not itself
   pin a platform (`Makefile:58-60`). Do not deploy, retag, emulate, or promote the arm64
   image as remediation.
2. **Confirmed deployed-release drift — Critical.** The running container is older than
   the audited revision and the new runtime-attestation implementation is not deployed.
   Consequently, the snapshot cannot supply the current release binding among immutable
   image ID, resolved configuration hash, Compose hash, and release key required by the
   runbook (`docs/operations-runbook.md:29-35`). Health alone proves neither readiness
   denial nor live-disabled state. Keep the current service paused; do not run connected
   profiles or any live path.

### High priority

3. **Confirmed provisioning-model drift — High.** The host was manually created, whereas
   Terraform describes a managed Droplet and attached firewall. Without reading state or
   cloud APIs (prohibited in this audit), resource ownership, import history, and the
   applicability of any plan are unknown. Never run `terraform apply` as a discovery or
   reconciliation step.
4. **Confirmed OS-assumption mismatch — High.** The snapshot reports Ubuntu 24.04, while
   the Terraform input contract accepts only the reviewed slug `ubuntu-26-04-x64`
   (`infra/digitalocean/variables.tf:5`). Because `main.tf` selects a numeric image ID
   instead (`infra/digitalocean/main.tf:1`), the configuration also lacks an internal
   assertion tying the deployed image ID to that slug. Whether 24.04 is acceptable must
   be decided and documented by the primary orchestrator before import, rebuild, or host
   replacement; this audit does not change the frozen image policy.
5. **Unknown firewall and host hardening — High.** The snapshot does not establish the
   DigitalOcean firewall attachment/rules, host firewall, SSH restrictions, patch level,
   Docker/Compose provenance, time synchronization, monitoring, swap, service-account
   sudo scope, Docker-group membership, or ownership/modes/symlink status of protected
   paths. These are explicit runbook prerequisites (`docs/operations-runbook.md:12-27`)
   and must not be inferred from a healthy container.
6. **Unknown rollback readiness — High.** The old deployment may predate the current
   root-private release directory, `last-good` pointer, exact Compose snapshot, deployment
   environment, and attestation format. The helper permits narrowly defined legacy
   environment shapes for first no-volume rollback (`infra/digitalocean/deploy-remote.sh:62-88`),
   but the snapshot does not show that the installed host artifacts meet them. A first
   current deployment could therefore fail closed before mutation or be unable to accept
   the prior release as rollback input; this must be established before attempting it.

### Medium priority

7. **Confirmed capacity variance — Medium.** The host has 2 GB RAM while Terraform's
   default size is `s-1vcpu-1gb` (`infra/digitalocean/variables.tf:6`). This is not by
   itself a safety defect, but it guarantees a plan discrepancy if defaults are used and
   must be resolved explicitly without downsizing by accident. CPU, disk, and swap remain
   unknown. Default Compose caps the service at 768 MB and 0.75 CPU
   (`docker-compose.yml:15-18`).
8. **Recovery execution and evidence are unverified — Medium.** The backup script makes a
   SQLite online backup, checks integrity, packages ledger/research evidence, hashes it,
   and encrypts it (`infra/digitalocean/backup.sh:3-25`). The restore helper decrypts and
   verifies an archive but does not install a database or restart a service
   (`infra/digitalocean/restore.sh:3-8`). The snapshot says nothing about backup schedule,
   encrypted off-host copies, retention, last success, restore-test history, available
   tooling, or recovery objectives. OAuth recovery is deliberately separate and does not
   belong in the evidence archive (`docs/disaster-recovery.md:11-15`).

## Dependency chain and critical path

1. **Preserve safety:** leave the existing service paused and avoid connected/live
   profiles. Capture only sanitized evidence under separate explicit host/cloud authority.
2. **Resolve infrastructure ownership:** decide whether the manual host will remain
   manually governed, be imported after an offline reviewed plan, or be replaced. Decide
   the reviewed OS and size inputs. This precedes any Terraform reconciliation.
3. **Audit host prerequisites:** establish firewall attachment, SSH and sudo policy,
   package/runtime versions, path ownership, Compose/helper hashes, and rollback artifacts.
   Any failed ownership or identity check is a stop condition.
4. **Prepare a compatible release:** build amd64 from the exact reviewed revision and
   pinned base image on a trusted builder; record its immutable image ID; verify the
   resolved configuration hash and exact Compose hash.
5. **Prove rollback before mutation:** validate the previous image is locally present and
   that the prior Compose/environment/release metadata match one accepted legacy or
   attested shape. Preserve the old image until the new paused release and rollback drill
   are independently accepted.
6. **Deploy only under separate authority:** use the root-owned helper. It must verify the
   candidate paused service before writing attestation and advancing `last-good`. A
   failure must leave or restore a verified paused state.
7. **Close recovery evidence:** demonstrate encrypted off-host backup and workstation-only
   restore verification without exposing credentials or production-ledger contents.

Steps 2–5 are the critical path. Connected probes, credential transfer, production-ledger
inspection, and every live-mode action are outside this audit and remain blocked.

## Rollback impacts

- Replacing/importing the host before resolving OS and capacity intent risks destructive
  Terraform action; review a saved, sanitized plan under separate authority and reject
  replacement or downsizing unless explicitly approved.
- Deploying the current code changes the release-record contract by adding the canonical
  attestation path. The helper intentionally accepts only two exact legacy environment
  shapes (`infra/digitalocean/deploy-remote.sh:75-87`); arbitrary older layouts are not a
  supported rollback source.
- Zero mounts means the reported default container has no ledger/OAuth persistence to
  migrate. It does **not** prove that protected host directories are absent, safe, or
  backed up. Do not delete or mount uninspected paths.
- Rollback success means the prior exact image, Compose, and environment are restored and
  again pass paused health, readiness-denial, and live-disabled checks. It does not renew
  evidence, authorize connected access, or permit live operation.

## Future verification commands (deferred; separate authority required)

Run these from trusted contexts only. Do not paste outputs containing identifiers,
environment values, paths to credential material, or production data into tickets or
logs. The placeholders are intentional.

### Offline repository/build verification

```sh
git rev-parse HEAD
git status --short
sha256sum docker-compose.yml
sed -n 's/^EXPECTED_COMPOSE_SHA256=//p' infra/digitalocean/deploy-remote.sh
docker image inspect --format '{{.Id}} {{.Architecture}} {{.Os}}' '<candidate-image-id>'
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
  --user 10001:10001 --tmpfs /tmp \
  --env LIVE_TRADING_ENABLED=false \
  --env PREDICTION_LIVE_ENABLED=false \
  --env TRADING_BOT__MONITORING__HOST=0.0.0.0 \
  --env TRADING_BOT__MONITORING__CONTAINER_LOOPBACK_PUBLISH=true \
  '<candidate-image-id>' config-hash --config /app/configs/shadow.yaml
docker compose config --images
```

Expected: exact reviewed revision; clean tree; matching Compose hashes; candidate reports
`amd64 linux`; one immutable `sha256:` image ID resolves for the default service; config
hash is the separately reviewed 64-character value.

### Authorized host verification (sanitized facts only)

```sh
uname -m
. /etc/os-release && printf '%s %s\n' "$ID" "$VERSION_ID"
timedatectl show -p NTPSynchronized --value
docker version --format '{{.Server.Version}}'
docker compose version --short
sudo stat -c '%n %U:%G %a %F' /opt /opt/trading-bot \
  /opt/trading-bot/docker-compose.yml /usr/local/sbin/trading-bot-deploy \
  /var/lib/trading-bot /var/log/trading-bot
sudo test ! -L /opt/trading-bot/docker-compose.yml
sudo sha256sum /opt/trading-bot/docker-compose.yml \
  /usr/local/sbin/trading-bot-deploy
sudo docker compose --project-directory /opt/trading-bot \
  --env-file /opt/trading-bot/.env -f /opt/trading-bot/docker-compose.yml ps
curl --disable --noproxy '*' --fail --silent http://127.0.0.1:8080/healthz >/dev/null
test "$(curl --disable --noproxy '*' --silent -o /dev/null -w '%{http_code}' \
  http://127.0.0.1:8080/readyz)" = 503
curl --disable --noproxy '*' --fail --silent http://127.0.0.1:8080/metrics \
  | grep -Fqx 'trading_bot_live_enabled 0.0'
sudo docker inspect --format '{{.Image}} {{json .Mounts}}' '<paused-container-id>'
```

Expected before deployment: x86_64/amd64 host, reviewed OS decision, synchronized clock,
reviewed runtime versions, exact root/service ownership and modes, known approved hashes,
one paused healthy container, readiness 503, live metric zero, and `[]` mounts. Inspect SSH,
sudo, firewall, monitoring, updates, swap, disk, and Docker-group membership through a
separately reviewed host-audit procedure; commands are deliberately omitted here because
their raw output can expose access policy and infrastructure identifiers.

### Authorized release/rollback verification

```sh
sudo test -f /opt/trading-bot/last-good
sudo test ! -L /opt/trading-bot/last-good
sudo stat -c '%U:%G %a %F' /opt/trading-bot/last-good
sudo sh -n /usr/local/sbin/trading-bot-deploy
TRADING_BOT_IMAGE='<sha256:amd64-image-id>' \
CONFIG_HASH='<resolved-config-hash>' DEPLOY_HOST='<approved-host>' \
DEPLOY_USER=tradingbot make deploy
```

After an authorized successful deployment, validate the release key using a
non-printing comparison, then check the attestation is a non-symlink regular file owned
by root, mode 0444, and byte-for-byte matches the canonical JSON expected by
`validate_release_attestation` (`infra/digitalocean/deploy-remote.sh:90-100`). Repeat the
three loopback checks above and confirm the executing image ID equals the candidate.
Exercise rollback only in an approved maintenance window; repeat those checks against
the prior immutable image and confirm `last-good` points to the restored release.

### Authorized recovery verification

```sh
TRADING_BOT_AGE_RECIPIENT_FILE='<reviewed-recipient-file>' \
BACKUP_OUTPUT='<approved-off-host-staging-path>/evidence.tar.age' make backup
TRADING_BOT_AGE_IDENTITY_FILE='<workstation-identity-file>' \
  ./infra/digitalocean/restore.sh '<downloaded-encrypted-archive>'
uv run pytest tests/deployment/test_backup_restore.py -q
```

Expected: encryption completes with restrictive permissions, the encrypted artifact is
copied to independently controlled storage, and verification succeeds on a trusted
operator workstation while the service remains paused. These commands are not a full
restore: document and separately rehearse database retention, compatible migration,
atomic installation, paused restart, and rollback. Never place the age identity on the
host (`docs/disaster-recovery.md:3-9`).

## Assumptions, deferred checks, and remaining blockers

Assumptions are limited to the sanitized snapshot: it is current as of the audit date;
“older” means not revision `a58f6eb`; “healthy” does not imply readiness or live-metric
results; “zero host mounts” describes the observed container only; and no other host or
cloud fact is inferred.

Completed locally: exact revision check, clean starting worktree check, static inspection
of the owned dependencies, source-path/line-reference validation, document diff check,
and owned-path-only status check. Runtime, deployment, Terraform, backup/restore, cloud,
host, architecture rebuild, and authenticated checks were deferred by task boundary.

Remaining external blockers are: approved infrastructure ownership model; reviewed OS
and size decision; cloud/firewall and host-hardening evidence; native amd64 immutable
image; exact installed Compose/helper and release metadata; proven pre-mutation rollback;
current attestation produced by the helper; paused health/readiness/live-metric evidence;
and demonstrated encrypted off-host backup plus workstation restore rehearsal. Until all
applicable gates are satisfied, the service stays paused and live operation remains
blocked.
