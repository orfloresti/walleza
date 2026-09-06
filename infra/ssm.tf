# Runtime secrets, all AWS SSM SecureString (design D10 — "All runtime
# secrets in SSM SecureString"). Terraform creates each parameter with a
# placeholder value so `terraform apply` can create the resource on a clean
# account with no secret material in source control or state history beyond
# the placeholder; the REAL value is written out of band afterwards with:
#
#   aws ssm put-parameter \
#     --name "/walleza/<environment>/<name>" \
#     --type SecureString --overwrite --value "<real secret>"
#
# `lifecycle.ignore_changes = [value]` means a subsequent `terraform apply`
# never reverts that out-of-band write back to the placeholder. Each
# parameter uses the account's default `alias/aws/ssm` KMS key (no
# customer-managed key provisioned in Phase 0 — the IAM policies in
# `lambda.tf`/`oidc.tf` grant `kms:Decrypt` on that default key).
#
# The Lambda execution role (`lambda.tf`) reads every parameter below except
# `migrations_database_url`; the GitHub Actions deploy role (`oidc.tf`) reads
# ONLY `migrations_database_url`, since the CI-run `alembic upgrade head`
# step is the sole caller of the direct (non-pooled) DDL connection
# (design D2/D3) — the Lambda's own runtime traffic uses the pooled
# `database_url` exclusively.

locals {
  ssm_prefix = "/walleza/${var.environment}"

  ssm_secret_parameters = {
    database_url = {
      description = "Supavisor transaction-pooler connection string (:6543), read by the Lambda execution role at cold start (design D2)."
    }
    migrations_database_url = {
      description = "Direct/session-mode Postgres connection string (:5432), read ONLY by the GitHub Actions deploy role to run `alembic upgrade head` (design D2/D3)."
    }
    jwt_secret = {
      description = "HS256 signing secret for access JWTs (design D8)."
    }
    google_client_secret = {
      description = "Google OAuth client secret (design D7). The paired client ID is public — see variables.tf's google_client_id."
    }
    worker_origin_token = {
      description = "Shared secret the Cloudflare Worker injects as X-Origin-Token; verified by OriginTokenMiddleware (design D9)."
    }
  }
}

resource "aws_ssm_parameter" "secret" {
  for_each = local.ssm_secret_parameters

  name        = "${local.ssm_prefix}/${each.key}"
  description = each.value.description
  type        = "SecureString"
  # Real value supplied out of band (see file header) — this placeholder
  # only satisfies the resource's required `value` attribute on first
  # create. It is never a usable credential.
  value = "REPLACE_OUT_OF_BAND"
  tags = {
    Project     = "walleza"
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  lifecycle {
    ignore_changes = [value]
  }
}

# Read back the CURRENT value of each secret (real value once set out of
# band, placeholder until then) so lambda.tf can wire it straight into the
# Lambda function's environment variables at apply time — mirroring
# backend/app/config.py's own documented mechanism ("deployment tooling is
# expected to resolve SSM parameters into the Lambda function's environment
# variables at deploy time").
data "aws_ssm_parameter" "secret" {
  for_each = local.ssm_secret_parameters

  name            = aws_ssm_parameter.secret[each.key].name
  with_decryption = true
}
