# Scheduler Lambda function + execution role (design D45, task 3.1).
#
# A SEPARATE function from `aws_lambda_function.backend` (infra/lambda.tf),
# built from the SAME deployment zip, handler `app.scheduler.handler`.
# Deliberately has NO `aws_lambda_function_url` resource and NO public
# `aws_lambda_permission` statement — its only invoker is the EventBridge
# rule in `infra/eventbridge.tf` (design D51). This is what makes
# "generation is unreachable from the public internet" a property of the
# resource graph rather than a code branch (design D45's rationale #1).
#
# `reserved_concurrent_executions = 1` is the platform-level guard against
# two overlapping scheduled runs (design D47/D51) — belt-and-braces
# alongside `SELECT ... FOR UPDATE SKIP LOCKED` in `app/recurring/
# generation.py` itself.

locals {
  scheduler_function_name = "walleza-scheduler-${var.environment}"

  # Minimal environment this function actually needs to open a DB session
  # and run `app.recurring.generation.run`/`run_reminders` (see
  # backend/app/scheduler.py and backend/app/config.py::Settings) —
  # deliberately NOT the backend function's full `local.non_secret_env`/
  # `local.secret_env` maps (no JWT/OAuth settings; the scheduler never
  # authenticates a caller). `WALLEZA_DATABASE_URL` reuses the SAME SSM
  # secret data source `infra/lambda.tf` already reads (`ssm.tf`), so both
  # functions always point at the same database with no drift risk.
  #
  # `WALLEZA_SES_FROM_ADDRESS`/`WALLEZA_SES_REGION`/`WALLEZA_WEB_APP_URL`
  # (design D54, PR4) are added here — not secrets, so plain env vars like
  # `google_client_id` on the backend function — so `app.notifications.ses`/
  # `app.recurring.generation.run_reminders` have somewhere to read the
  # From address, SES region, and reminder-body web app link from, once
  # this environment's SES identity is actually verified (tasks 4.14-4.18).
  scheduler_env = {
    WALLEZA_ENVIRONMENT = var.environment
    WALLEZA_APP_VERSION = var.app_version
    WALLEZA_COMMIT_SHA  = "unknown"

    WALLEZA_DATABASE_URL = data.aws_ssm_parameter.secret["database_url"].value

    WALLEZA_SES_FROM_ADDRESS = var.ses_from_address
    WALLEZA_SES_REGION       = var.aws_region
    WALLEZA_WEB_APP_URL      = var.web_app_url
  }
}

resource "aws_cloudwatch_log_group" "scheduler" {
  name              = "/aws/lambda/${local.scheduler_function_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Project     = "walleza"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "scheduler_exec" {
  name = "walleza-scheduler-exec-${var.environment}"
  # Same trust policy shape as `aws_iam_role.lambda_exec` (infra/lambda.tf)
  # — any Lambda function in this account assumes it via the `lambda.amazonaws.com`
  # service principal, mirrored here rather than shared, per design D45's
  # IAM capability-separation rationale (rationale #2): the public HTTP role
  # and this role must never be the same resource.
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = "walleza"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# CloudWatch Logs only (create/put log events into the log group above).
# Deliberately no `lambda_ssm_read`/`lambda_s3_receipts`-equivalent policy
# here in PR3 scope, and no `ses:*` grant either — the SES send policy
# (design D53) is PR4's job, attached to this SAME role once it lands.
resource "aws_iam_role_policy_attachment" "scheduler_basic_execution" {
  role       = aws_iam_role.scheduler_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_lambda_function" "scheduler" {
  function_name = local.scheduler_function_name
  role          = aws_iam_role.scheduler_exec.arn

  # Same zip as the backend function (task 3.1) — first-create-only
  # payload, replaced on every real deploy by the second
  # `aws lambda update-function-code` call added to `.github/workflows/
  # ci-cd.yml`'s existing "Update Lambda function code" step.
  filename         = var.lambda_package_path
  source_code_hash = filebase64sha256(var.lambda_package_path)

  handler       = "app.scheduler.handler"
  runtime       = "python3.13"
  architectures = ["arm64"]
  memory_size   = var.lambda_memory_size_mb
  # 300s vs. the HTTP function's `var.lambda_timeout_seconds` (15s,
  # design D1) — design D45's rationale #3: the generation run iterates
  # every workspace and needs headroom no Function URL request could ever
  # hold open.
  timeout = 300

  # Design D47/D51 calls for `reserved_concurrent_executions = 1` here as a
  # platform-level guard against two overlapping scheduled runs, on top of
  # the per-recurrence `SELECT ... FOR UPDATE SKIP LOCKED` row lock in
  # `app/recurring/generation.py`. PERMANENT DEVIATION (documented, not
  # silent, decision accepted by the project owner): this AWS account's
  # total Lambda concurrency limit is fixed at 10 and will not be raised —
  # the AWS-wide floor of 10 unreserved executions makes ANY reservation on
  # ANY function impossible at that ceiling, so this setting can never be
  # applied on this account. Correctness does not depend on it: D47's
  # actual idempotency/concurrency guarantee is the DB row lock plus
  # `recurring_occurrence`'s primary key (both shipped and tested in PR2),
  # which is sufficient on its own per design's own risk analysis. This
  # line is intentionally omitted for good, not pending anything.

  environment {
    variables = local.scheduler_env
  }

  tags = {
    Project     = "walleza"
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  depends_on = [
    aws_iam_role_policy_attachment.scheduler_basic_execution,
    aws_cloudwatch_log_group.scheduler,
  ]

  lifecycle {
    # Same rationale as `aws_lambda_function.backend` (infra/lambda.tf):
    # CI/CD owns the deployed code payload after the first apply, and the
    # version-stamp variables get refreshed the same way the backend
    # function's are — a plain `terraform apply` must not fight that.
    ignore_changes = [
      filename,
      source_code_hash,
      environment,
    ]
  }
}
