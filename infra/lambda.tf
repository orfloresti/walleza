# Backend Lambda function + Function URL + execution role (task 7.3).
#
# Design D1: Mangum + Function URL (payload v2), `lifespan="off"`, arm64,
# 1024 MB (`var.lambda_memory_size_mb`), no provisioned concurrency.
# Design D9: Function URL `AuthType: NONE` (publicly reachable), locked down
# to Cloudflare-Worker-proxied traffic only by `OriginTokenMiddleware`
# checking `X-Origin-Token` — NOT by IAM/SigV4 (`AuthType: NONE` is what
# makes that header check possible; `AuthType: AWS_IAM` would require SigV4
# signing the Worker cannot do and would fail closed regardless of the
# header).

locals {
  function_name = "walleza-backend-${var.environment}"

  # Non-secret configuration, passed straight through as plain Lambda
  # environment variables (mirrors backend/app/config.py's `Settings`
  # field names exactly, via the `WALLEZA_` env-var prefix it reads).
  non_secret_env = {
    WALLEZA_ENVIRONMENT = var.environment
    WALLEZA_APP_VERSION = var.app_version
    WALLEZA_COMMIT_SHA  = "unknown"

    WALLEZA_JWT_ISSUER              = var.jwt_issuer
    WALLEZA_JWT_AUDIENCE            = var.jwt_audience
    WALLEZA_JWT_KID                 = var.jwt_kid
    WALLEZA_JWT_ACCESS_TTL_SECONDS  = tostring(var.jwt_access_ttl_seconds)
    WALLEZA_OAUTH_STATE_TTL_SECONDS = tostring(var.oauth_state_ttl_seconds)
    WALLEZA_REFRESH_TTL_DAYS        = tostring(var.refresh_ttl_days)

    WALLEZA_GOOGLE_CLIENT_ID              = var.google_client_id
    WALLEZA_GOOGLE_JWKS_URL               = var.google_jwks_url
    WALLEZA_GOOGLE_ISSUER                 = var.google_issuer
    WALLEZA_GOOGLE_AUTHORIZATION_ENDPOINT = var.google_authorization_endpoint
    WALLEZA_GOOGLE_TOKEN_ENDPOINT         = var.google_token_endpoint
    WALLEZA_GOOGLE_REDIRECT_URI           = var.google_redirect_uri
  }

  # Secrets resolved from SSM at apply time (see ssm.tf), excluding
  # `migrations_database_url` — that one is read only by the CI/CD deploy
  # role (oidc.tf), never by the Lambda itself.
  secret_env = {
    WALLEZA_DATABASE_URL         = data.aws_ssm_parameter.secret["database_url"].value
    WALLEZA_JWT_SECRET           = data.aws_ssm_parameter.secret["jwt_secret"].value
    WALLEZA_GOOGLE_CLIENT_SECRET = data.aws_ssm_parameter.secret["google_client_secret"].value
    WALLEZA_WORKER_ORIGIN_TOKEN  = data.aws_ssm_parameter.secret["worker_origin_token"].value
  }
}

data "aws_caller_identity" "current" {}

resource "aws_cloudwatch_log_group" "backend" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Project     = "walleza"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_exec" {
  name               = "walleza-lambda-exec-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = "walleza"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# CloudWatch Logs (create/put log events into the log group above).
resource "aws_iam_role_policy_attachment" "lambda_basic_execution" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# The runtime itself does not call SSM directly (design D10 note in
# backend/app/config.py — secrets arrive as already-resolved environment
# variables), but the execution role still needs read access to the SSM
# parameters/KMS key so a FUTURE cold-start `boto3` refresh path (explicitly
# left open by that module's docstring) is not blocked by IAM alone.
data "aws_iam_policy_document" "lambda_ssm_read" {
  statement {
    sid     = "ReadOwnSecrets"
    effect  = "Allow"
    actions = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = [
      for k in keys(local.ssm_secret_parameters) : aws_ssm_parameter.secret[k].arn
      if k != "migrations_database_url"
    ]
  }

  statement {
    sid       = "DecryptWithDefaultSsmKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"]
  }
}

resource "aws_iam_role_policy" "lambda_ssm_read" {
  name   = "ssm-read"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.lambda_ssm_read.json
}

resource "aws_lambda_function" "backend" {
  function_name = local.function_name
  role          = aws_iam_role.lambda_exec.arn

  # First-create-only payload — every real deploy afterwards replaces this
  # via `aws lambda update-function-code` in the CI/CD workflow (see this
  # file's header comment and variables.tf's lambda_package_path doc).
  filename         = var.lambda_package_path
  source_code_hash = filebase64sha256(var.lambda_package_path)

  handler       = "app.handler.handler"
  runtime       = "python3.13"
  architectures = ["arm64"]
  memory_size   = var.lambda_memory_size_mb
  timeout       = var.lambda_timeout_seconds

  environment {
    variables = merge(local.non_secret_env, local.secret_env)
  }

  tags = {
    Project     = "walleza"
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  depends_on = [
    aws_iam_role_policy_attachment.lambda_basic_execution,
    aws_cloudwatch_log_group.backend,
  ]

  lifecycle {
    # The CI/CD workflow owns the deployed code and the two version-stamp
    # variables after the first apply (`aws lambda update-function-code`,
    # then `update-function-configuration` to set WALLEZA_APP_VERSION/
    # WALLEZA_COMMIT_SHA — see ci-cd.yml's "Record deployed version/commit"
    # step). Terraform re-applying its own placeholder zip and initial
    # version stamp on every plan would fight that and roll back whatever
    # CI just shipped, so both the code payload and the WHOLE `environment`
    # block (Terraform's `ignore_changes` cannot target one map key inside
    # a nested block) are ignored after creation. Changing a non-secret
    # config variable in `variables.tf` after the first apply therefore
    # requires either a one-time `terraform apply -replace` or a manual
    # `aws lambda update-function-configuration` — documented in
    # `infra/README.md`.
    ignore_changes = [
      filename,
      source_code_hash,
      environment,
    ]
  }
}

resource "aws_lambda_function_url" "backend" {
  function_name      = aws_lambda_function.backend.function_name
  authorization_type = "NONE"

  cors {
    # Same-origin via the Cloudflare Worker proxy (design D9) — the
    # browser never calls this Function URL directly, so CORS is left at
    # its most restrictive useful default rather than opened up.
    allow_origins = []
    allow_methods = ["GET", "POST"]
  }
}

# Required whenever a Function URL uses `authorization_type = "NONE"`:
# without this resource-based policy statement, invoking the Function URL
# fails with "Forbidden" even though IAM auth is disabled — enforcement is
# entirely in the app's OriginTokenMiddleware (design D9), not here.
resource "aws_lambda_permission" "function_url_public" {
  statement_id           = "AllowPublicFunctionUrlInvoke"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.backend.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}
