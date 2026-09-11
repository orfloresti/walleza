# Input variables for the walleza platform root module.
#
# This module is applied once per environment (`terraform apply
# -var environment=staging`, then again with `-var environment=production`),
# not with Terraform workspaces — every resource name/SSM path already
# includes `var.environment`, so two applies produce two fully independent
# sets of resources (own Lambda, own IAM roles, own SSM parameters), matching
# design D10's `/walleza/<env>/<name>` SSM layout and the CI workflow's
# per-GitHub-Environment (`staging`/`production`) deploy targets.

variable "environment" {
  description = "Deployment environment this apply targets. Drives resource names and SSM parameter paths (design D10)."
  type        = string

  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be \"staging\" or \"production\"."
  }
}

variable "aws_region" {
  description = "AWS region hosting the Lambda function and SSM parameters."
  type        = string
  default     = "us-east-1"
}

variable "github_repository" {
  description = <<-EOT
    GitHub repository in "<owner>/<repo>" form, used to scope the GitHub
    Actions OIDC trust condition (design D10:
    `sub = repo:<owner>/walleza:environment:<environment>`).
  EOT
  type        = string
  default     = "orfloresti/walleza"
}

# GitHub's "immutable subject claims" change (see
# https://github.blog/changelog/2026-04-23-immutable-subject-claims-for-github-actions-oidc-tokens/):
# repos CREATED AFTER 2026-07-15 — this one included, created 2026-09-06 —
# get a `sub` claim of the form `repo:OWNER@OWNER_ID/REPO@REPO_ID:environment:NAME`
# by default, not the older `repo:OWNER/REPO:environment:NAME` this module's
# first real apply (PR6) used and had rejected with a real
# `sts:AssumeRoleWithWebIdentity` "Not authorized" error — confirmed via
# CloudTrail's logged `userIdentity.principalId` on the actual failed call.
# These IDs are immutable per GitHub account/repo (survive a rename), fetched
# once via `gh api users/orfloresti --jq .id` / `gh api repos/orfloresti/walleza --jq .id`.
variable "github_owner_id" {
  description = "Immutable numeric ID of the GitHub account/org owning this repository."
  type        = string
  default     = "14968496"
}

variable "github_repo_id" {
  description = "Immutable numeric ID of this GitHub repository."
  type        = string
  default     = "1359433203"
}

variable "create_github_oidc_provider" {
  description = <<-EOT
    Whether this apply should create the AWS account's GitHub Actions OIDC
    identity provider (`infra/oidc.tf`). An AWS account can only register
    `token.actions.githubusercontent.com` ONCE — set this to `true` on the
    first environment ever applied (e.g. `staging`, applied first) and
    `false` on every subsequent environment apply (e.g. `production`), which
    instead references the provider the first apply created via a data
    source. See `infra/README.md`'s "Bootstrap order" section.
  EOT
  type        = bool
  default     = false
}

variable "lambda_package_path" {
  description = <<-EOT
    Path to the zipped Lambda deployment package (Mangum-wrapped FastAPI
    app + dependencies). The CI/CD deploy job (`.github/workflows/ci-cd.yml`)
    builds and pushes real code via `aws lambda update-function-code` on
    every deploy; this path only needs to exist and be valid the FIRST time
    `terraform apply` creates the function (Lambda requires a non-empty
    `filename`/code payload at creation time). A minimal placeholder archive
    is enough — see `infra/README.md`'s "First apply" section.
  EOT
  type        = string
  default     = "./placeholder-lambda.zip"
}

variable "lambda_memory_size_mb" {
  description = "Lambda memory in MB (design D1: 1024 MB, no provisioned concurrency)."
  type        = number
  default     = 1024
}

variable "lambda_timeout_seconds" {
  description = "Lambda invocation timeout."
  type        = number
  default     = 15
}

variable "log_retention_days" {
  description = "CloudWatch Logs retention for the Lambda function's log group."
  type        = number
  default     = 30
}

# --- Non-secret application configuration -----------------------------
# Mirrors backend/app/config.py's `Settings` field names 1:1 (minus the
# fields sourced from SSM SecureString in ssm.tf/lambda.tf below). These
# are plain Lambda environment variables, not secrets, so they are ordinary
# Terraform variables rather than SSM parameters.

variable "app_version" {
  description = "Initial WALLEZA_APP_VERSION value; the CI/CD deploy job overwrites this on every deploy (see ci-cd.yml's \"Record deployed version/commit\" step)."
  type        = string
  default     = "0.0.0-unreleased"
}

variable "jwt_issuer" {
  type    = string
  default = "walleza"
}

variable "jwt_audience" {
  type    = string
  default = "walleza-web"
}

variable "jwt_kid" {
  description = "Key ID header for issued access JWTs (design D8 — present from day one for future key rotation)."
  type        = string
  default     = "prod-key-1"
}

variable "jwt_access_ttl_seconds" {
  type    = number
  default = 900
}

variable "oauth_state_ttl_seconds" {
  type    = number
  default = 600
}

variable "refresh_ttl_days" {
  type    = number
  default = 30
}

variable "google_client_id" {
  description = "Google OAuth client ID. Public per design D10 (\"Google client ID is public\") — not a secret, but still environment-specific (staging and production use distinct Google OAuth clients per design D10/proposal)."
  type        = string
}

variable "google_jwks_url" {
  type    = string
  default = "https://www.googleapis.com/oauth2/v3/certs"
}

variable "google_issuer" {
  type    = string
  default = "https://accounts.google.com"
}

variable "google_authorization_endpoint" {
  type    = string
  default = "https://accounts.google.com/o/oauth2/v2/auth"
}

variable "google_token_endpoint" {
  type    = string
  default = "https://oauth2.googleapis.com/token"
}

variable "google_redirect_uri" {
  description = "Must exactly match a redirect URI registered on this environment's Google OAuth client. Same-origin via the Cloudflare Worker (design D9), e.g. https://walleza.orfloresti.dev/api/auth/callback for production."
  type        = string
}

# --- Phase 2: Categories & Manual Transactions (S3 receipts bucket) ---

variable "web_origin" {
  description = <<-EOT
    Browser origin allowed to call the receipts S3 bucket directly (CORS —
    `infra/s3.tf`'s `aws_s3_bucket_cors_configuration.receipts`), for the
    presigned-POST upload and presigned-GET download flow (design D24/D25/
    D26). Required, per-environment, no default — same shape as
    `google_redirect_uri` above, e.g. https://walleza.orfloresti.dev for
    production. A wrong value fails only in the browser, at upload time, as
    an opaque CORS error (see infra/README.md's smoke-test note).
  EOT
  type        = string
}

# --- Phase 4: Recurring & Scheduled Transactions (EventBridge schedule) ---

variable "generation_schedule_enabled" {
  description = <<-EOT
    Whether the daily occurrence-generation EventBridge rule
    (`aws_cloudwatch_event_rule.generation`, infra/eventbridge.tf) is
    `ENABLED` or `DISABLED` (design D51). Defaults to `false` so the first
    `terraform apply` per environment cannot fire generation before the
    deploy/migration/smoke-test sequence in design's Migration/Rollout
    section completes — flip to `true` and re-apply once smoke-tested
    (tasks 3.9/3.11).
  EOT
  type        = bool
  default     = false
}

variable "generation_schedule_expression" {
  description = <<-EOT
    EventBridge schedule expression for the daily occurrence-generation run
    (design D51). `cron(0 6 * * ? *)` is 06:00 UTC daily, which is stably
    00:00 in `America/Mexico_City` (Mexico abolished DST in 2022, permanent
    UTC-6).
  EOT
  type        = string
  default     = "cron(0 6 * * ? *)"
}

# --- Phase 4: Recurring & Scheduled Transactions (SES reminders) ------

variable "ses_domain" {
  description = <<-EOT
    Per-environment SES domain identity (design D52): "orfloresti.dev" for
    production, "staging.orfloresti.dev" for staging. Required, no default
    — this module is applied twice into the same AWS account/region, and
    two applies declaring the same domain would contend for one global SES
    resource across two independent Terraform states.
  EOT
  type        = string
}

variable "ses_from_address" {
  description = <<-EOT
    Exact From address the scheduler function's execution role is permitted
    to send as (design D53's `ses:FromAddress` IAM condition — the true
    ceiling on what the deployed code can ever send as). Required, no
    default, e.g. reminders@orfloresti.dev for production.
  EOT
  type        = string
}

variable "ses_sandbox_verified_recipients" {
  description = <<-EOT
    Addresses to verify as individual SES email identities (design D52).
    Required while this environment's SES account remains in the sandbox:
    a sandboxed account can only send TO a verified identity, not merely
    FROM a verified domain. Each address triggers a real click-the-link
    verification email — Terraform cannot complete that step. Required, no
    default.
  EOT
  type        = list(string)
}

variable "web_app_url" {
  description = <<-EOT
    Frontend origin surfaced in the reminder email body (design D54's Data
    Flow diagram) so a recipient can click through to manage the recurrence
    that generated the reminder. Required, no default, e.g.
    https://walleza.orfloresti.dev for production.
  EOT
  type        = string
}
