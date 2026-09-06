# GitHub Actions OIDC federation (task 7.3 / design D10 — "AWS via OIDC,
# trust condition `sub = repo:<owner>/walleza:environment:production`", no
# long-lived static AWS credentials stored anywhere in this repository).
#
# `aws_iam_openid_connect_provider` is an AWS-ACCOUNT-WIDE resource — an
# account can only register `token.actions.githubusercontent.com` once. See
# `variables.tf`'s `create_github_oidc_provider` doc and
# `infra/README.md`'s "Bootstrap order" section for which environment apply
# owns creating it.

# SHA-1 fingerprint of the root CA at the top of
# token.actions.githubusercontent.com's current certificate chain (ISRG
# Root X1, via Let's Encrypt intermediate "YR2" — verified directly against
# the live endpoint during this PR with
# `openssl s_client -showcerts -connect token.actions.githubusercontent.com:443`,
# not copied from a possibly-stale tutorial value). AWS's IAM OIDC provider
# has validated against its own trusted CA bundle rather than this field
# since mid-2023, so a future CA rotation on GitHub's side will not silently
# break authentication — `thumbprint_list` only has to stay a syntactically
# valid 40-character SHA-1 hex string.
locals {
  github_oidc_thumbprint = "ab9d0263244dd0326eb67015705a667e79cfe998"
}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 1 : 0

  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [local.github_oidc_thumbprint]

  tags = {
    Project   = "walleza"
    ManagedBy = "terraform"
  }
}

# When THIS apply didn't create the provider (var.create_github_oidc_provider
# = false), look it up instead — it must already exist from whichever
# environment applied first.
data "aws_iam_openid_connect_provider" "github" {
  count = var.create_github_oidc_provider ? 0 : 1

  url = "https://token.actions.githubusercontent.com"
}

locals {
  github_oidc_provider_arn = var.create_github_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.github[0].arn
}

# Trust policy: only workflow runs executing under THIS repository's THIS
# GitHub Environment (`staging` or `production`, matching var.environment)
# may assume this role — not any branch, not any workflow, not the other
# environment. `aud` must be the fixed STS audience GitHub's OIDC token
# uses.
data "aws_iam_policy_document" "github_actions_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.github_oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.github_repository}:environment:${var.environment}"]
    }
  }
}

resource "aws_iam_role" "github_actions_deploy" {
  name               = "walleza-github-actions-deploy-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.github_actions_assume_role.json

  tags = {
    Project     = "walleza"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# Scoped to exactly what ci-cd.yml's `deploy` job does: read the migration
# DB URL, update this environment's Lambda code/config, and wait for the
# update to finish. No `lambda:CreateFunction`/`iam:*`/broad `ssm:*` — the
# Lambda function and its IAM role are provisioned by `terraform apply`
# (lambda.tf), never by CI.
data "aws_iam_policy_document" "github_actions_deploy" {
  statement {
    sid       = "ReadMigrationsDatabaseUrl"
    effect    = "Allow"
    actions   = ["ssm:GetParameter"]
    resources = [aws_ssm_parameter.secret["migrations_database_url"].arn]
  }

  statement {
    sid       = "DecryptWithDefaultSsmKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"]
  }

  statement {
    sid    = "DeployLambdaCode"
    effect = "Allow"
    actions = [
      "lambda:UpdateFunctionCode",
      "lambda:UpdateFunctionConfiguration",
      "lambda:GetFunction",
      "lambda:GetFunctionConfiguration",
    ]
    resources = [aws_lambda_function.backend.arn]
  }
}

resource "aws_iam_role_policy" "github_actions_deploy" {
  name   = "deploy"
  role   = aws_iam_role.github_actions_deploy.id
  policy = data.aws_iam_policy_document.github_actions_deploy.json
}
