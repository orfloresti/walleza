# Provider requirements + AWS provider config for this environment's apply
# (task 7.3). See README.md for the Terraform-over-SAM decision. Real AWS
# resources (Lambda + Function URL, IAM/OIDC roles, SSM params) are declared
# in lambda.tf/oidc.tf/ssm.tf; variables.tf documents the per-environment
# apply model (`-var environment=staging`, then `-var environment=production`).
#
# The `cloudflare` provider is still only pinned here, not configured or
# used yet: the Worker/DNS resources it would provision are the staging
# verification + `walleza.orfloresti.dev` DNS cutover work explicitly
# scoped to PR6 in `sdd/phase-0-platform-foundation/tasks` (task 7.3 itself
# only lists "Lambda + Function URL, IAM/OIDC roles, SSM params" — no
# Cloudflare resource). The Worker is deployed today by Wrangler directly
# from `.github/workflows/ci-cd.yml` (`npx wrangler deploy`), reading
# `frontend/wrangler.toml`.

terraform {
  required_version = ">= 1.9.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }

  # backend "s3" { ... } — remote state config is a documented follow-up
  # (see README.md's "Remote state" section); no S3 bucket/DynamoDB lock
  # table exists in this sandbox to point it at, and every command in this
  # PR was reviewed against local/in-memory state only.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "walleza"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
