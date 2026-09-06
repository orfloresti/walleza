# Infrastructure

## Decision: Terraform (not AWS SAM)

**Chosen tool:** [Terraform](https://developer.hashicorp.com/terraform)

**Rejected:** AWS SAM

**Rationale:** This phase's design (`sdd/phase-0-platform-foundation/design`,
decisions D1/D9/D10) provisions resources across three providers, not just
AWS Lambda:

- **AWS** — Lambda function (Mangum-wrapped FastAPI), Function URL, IAM
  roles, the GitHub OIDC trust role, and SSM `SecureString` parameters.
- **Cloudflare** — the Worker that serves static assets and proxies `/api/*`,
  plus the `walleza.orfloresti.dev` DNS record.
- **Supabase** — the Postgres project/connection this backend depends on
  (to whatever extent Supabase's Terraform provider or a data source covers
  it; anything it cannot cover stays a documented manual step).

AWS SAM only models AWS resources (and mainly Lambda-centric ones at that).
Using SAM here would mean a second tool plus hand-rolled scripts for
Cloudflare and Supabase, with two sources of truth for one deployable stack.
Terraform has mature providers for all three (`hashicorp/aws`,
`cloudflare/cloudflare`, and a community/official Supabase provider) and can
express the whole platform's infrastructure as one state, one plan, and one
apply. That single-state property is the deciding factor over SAM's
Lambda-native ergonomics.

This decision was deferred from `design.md`'s open questions to this task
(`sdd-tasks` → task 1.1) precisely because it does not block the application
design — only the deployment mechanics in PR5.

## Status

PR5 (task 7.3) implements the AWS side of this module: the backend Lambda
function, its Function URL, the Lambda execution role, the GitHub Actions
OIDC trust role used by `.github/workflows/ci-cd.yml`'s deploy job, and the
SSM SecureString parameters that hold every runtime secret
`backend/app/config.py`'s `Settings` reads. **No `terraform apply` has been
run against a real AWS account in this sandbox** — there are no AWS
credentials here, and the CLI itself is not installed (see "Local
validation caveat" below). The HCL was hand-reviewed instead; `terraform
validate`/`terraform fmt -check` should be run as the first step of
whichever pipeline/workstation does have the CLI, before the first real
apply.

Cloudflare Worker/DNS resources are explicitly **not** part of this PR:
task 7.3's own task text lists only "Lambda + Function URL, IAM/OIDC roles,
SSM params", and the DNS cutover to `walleza.orfloresti.dev` is PR6 scope
per the tasks doc. The Worker is deployed today directly by Wrangler from
the CI/CD workflow (`npx wrangler deploy`, `frontend/wrangler.toml`), not
by Terraform — see that file's header comment. A `cloudflare.tf` module may
still be added later if the Worker/DNS lifecycle needs to move under
Terraform's state, but that is out of this phase's scope.

## Actual layout

```
infra/
├── README.md              # this file
├── main.tf                # terraform block, required_providers, aws provider config
├── variables.tf           # environment, aws_region, github_repository, non-secret app config
├── outputs.tf             # function URL/ARN, deploy role ARN, OIDC provider ARN, SSM names
├── lambda.tf              # Lambda function, Function URL, execution role + SSM/KMS read policy
├── oidc.tf                # GitHub OIDC provider (bootstrap-once) + deploy role + policy
└── ssm.tf                 # SecureString parameters (placeholder values only, never real secrets)
```

## Apply model: one apply per environment

This is a single root module applied TWICE, once per environment, with
`-var environment=staging` and again with `-var environment=production` —
not Terraform workspaces. Every resource name and SSM path already includes
`var.environment` (`walleza-backend-staging` vs. `walleza-backend-production`,
`/walleza/staging/...` vs. `/walleza/production/...`), so the two applies
produce fully independent infrastructure with separate state (e.g. two
separate `-state=` files, or two backend `key`s once the remote backend
below is configured).

## Bootstrap order (`create_github_oidc_provider`)

`token.actions.githubusercontent.com` can only be registered ONCE per AWS
account. Apply **staging first** with `create_github_oidc_provider = true`;
apply **production second** with it left at its default `false` (it then
looks the same provider up via a data source — see `oidc.tf`). Reversing
the order works identically as long as exactly one apply sets it `true`.

## First apply: the Lambda's initial code payload

`aws_lambda_function` requires a real, non-empty deployment package at
creation time — Terraform cannot create a Lambda with no code. Before the
first `terraform apply` per environment, produce a minimal placeholder zip
at the path `var.lambda_package_path` points to (default
`./placeholder-lambda.zip`), for example:

```bash
mkdir -p /tmp/placeholder-lambda && cd /tmp/placeholder-lambda
printf 'def handler(event, context):\n    return {"statusCode": 200, "body": "placeholder"}\n' > handler.py
zip -r /path/to/infra/placeholder-lambda.zip handler.py
```

`.github/workflows/ci-cd.yml`'s deploy job overwrites this with the real
Mangum-wrapped FastAPI package on every subsequent deploy via
`aws lambda update-function-code` — Terraform's own copy of the code is
permanently ignored after creation (see `lambda.tf`'s `lifecycle.ignore_changes`
and its comment for why).

## After the first apply: writing real secrets

Every parameter in `outputs.tf`'s `ssm_parameter_names` is created with the
placeholder value `REPLACE_OUT_OF_BAND`. Set the real value for each with:

```bash
aws ssm put-parameter \
  --name "/walleza/<environment>/<name>" \
  --type SecureString --overwrite --value "<real secret>"
```

Terraform's `lifecycle.ignore_changes` on each parameter's `value` means a
later `terraform apply` never reverts this back to the placeholder — but it
also means the Lambda's environment variables (populated by a `data
"aws_ssm_parameter"` read of the CURRENT value at apply time, see
`lambda.tf`) only pick up a freshly-written secret on the NEXT
`terraform apply`, not automatically. Re-run `terraform apply` once after
writing real secrets for the first time.

## Wiring the GitHub Environment

For each of the `staging`/`production` GitHub Environments (Settings >
Environments):

- Variable `AWS_DEPLOY_ROLE_ARN` = this apply's
  `github_actions_deploy_role_arn` output.
- Repository secret `CLOUDFLARE_API_TOKEN` (design D10 — the one long-lived
  secret this project stores, since Cloudflare has no OIDC federation).
- Required reviewers stay off in Phase 0 (design D10 — "a one-switch
  escalation"); branch protection (PR + green required checks) plus the
  workflow's own `needs:` is the gate.

## Prerequisites

- Terraform CLI `>= 1.9.0` (not installed in this sandbox — see "Local
  validation caveat" below)
- AWS credentials with permission to manage the resources this module
  declares (IAM, Lambda, SSM, the account-wide OIDC provider)
- A Cloudflare API token scoped to the `orfloresti.dev` zone, stored as
  `CLOUDFLARE_API_TOKEN` (used by CI's Wrangler deploy step, not by
  Terraform — see "Status" above)

## Remote state

Not configured yet (`main.tf`'s `terraform { backend "s3" {} }` stays
commented out) — no S3 bucket or DynamoDB lock table exists in this
sandbox to point it at, and provisioning one is itself a `terraform apply`
against the same account this module manages (a well-known bootstrapping
chicken-and-egg problem, usually solved with a small separate
state-bucket-only module applied once, by hand, before this one). Tracked
as a follow-up; local/in-memory state is acceptable for however long this
project needs a single operator applying from one machine.

## Local validation caveat

No Terraform CLI is installed in this sandbox, matching PR1's task 1.1
caveat for `main.tf`'s original provider-only stub. Every file added in
this PR was reviewed by hand for valid HCL syntax, correct resource/data
source arguments (cross-checked against the `hashicorp/aws` provider's
documented schema), and internal consistency (variable names, resource
references, `for_each`/`count` usage). `terraform validate` and
`terraform fmt -check` should both be run as the very first step once a
Terraform CLI is available — before any real `terraform plan`/`apply` —
and any formatting or schema issue they surface fixed before this module is
ever applied against a real account.
