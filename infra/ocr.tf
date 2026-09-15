# OCR worker Lambda + execution role + S3 event notification (design
# D135/D136, sdd/phase-9-photo-capture, Unit 7 — ISOLATED, highest
# blast-radius risk in this phase).
#
# A THIRD function, separate from `aws_lambda_function.backend` (lambda.tf)
# and `aws_lambda_function.scheduler` (scheduler.tf), built from the SAME
# deployment zip, handler `app.ocr_worker.handler`. Triggered by an S3
# `ObjectCreated` event on the receipts bucket (`infra/s3.tf`) rather than
# HTTP or EventBridge — its own execution role, never shared with the other
# two, per design D45's IAM capability-separation rationale (mirrored here
# for a third time, same as `scheduler_exec` mirrors `lambda_exec`).
#
# ============================================================================
# MANDATORY PRE-APPLY OPERATOR CHECK (design D136) — READ BEFORE RUNNING
# `terraform apply` FOR THE FIRST TIME AGAINST A REAL ENVIRONMENT.
#
# `aws_s3_bucket_notification.receipts` below maps to a single
# `PutBucketNotificationConfiguration` API call, which REPLACES the entire
# notification configuration of the bucket it targets. Terraform has no
# prior state for this resource (it has never managed it), so `terraform
# plan` will show a clean `+ create` regardless of whether the live bucket
# already has some out-of-band notification configuration — plan output
# CANNOT reveal what it is about to overwrite.
#
# Before the FIRST EVER apply of this resource, run:
#
#   aws s3api get-bucket-notification-configuration \
#     --bucket walleza-receipts-<environment>-<account-id>
#
# Expected output: `{}` (empty), or a JSON object with no
# `LambdaFunctionConfigurations` key. If it returns anything else, a
# notification configuration was created out-of-band and applying this
# resource would silently destroy it — STOP and reconcile by hand before
# proceeding.
# ============================================================================

locals {
  ocr_function_name = "walleza-ocr-${var.environment}"

  # Minimal environment this function needs to open a DB session, call
  # Textract, and read the triggering S3 object's bucket (see
  # backend/app/ocr_worker.py and backend/app/config.py::Settings) —
  # deliberately NOT the backend function's full env map, mirroring
  # `scheduler_env`'s same minimalism (no JWT/OAuth settings; this function
  # never authenticates a caller either).
  #
  # `WALLEZA_DATABASE_URL` reuses the SAME SSM secret data source
  # `infra/lambda.tf`/`infra/scheduler.tf` already read (`ssm.tf`), so all
  # three functions always point at the same database with no drift risk.
  ocr_env = {
    WALLEZA_ENVIRONMENT = var.environment
    WALLEZA_APP_VERSION = var.app_version
    WALLEZA_COMMIT_SHA  = "unknown"

    WALLEZA_DATABASE_URL = data.aws_ssm_parameter.secret["database_url"].value

    WALLEZA_S3_RECEIPTS_BUCKET = aws_s3_bucket.receipts.bucket
    # Field name is `ocr_textract_region` on `Settings`, so the resolved env
    # var is `WALLEZA_OCR_TEXTRACT_REGION` (pydantic-settings' env_prefix +
    # field name) — design D135's prose shorthand ("WALLEZA_TEXTRACT_REGION")
    # is corrected here to match `backend/app/config.py` exactly.
    WALLEZA_OCR_TEXTRACT_REGION = var.ocr_textract_region
  }
}

resource "aws_cloudwatch_log_group" "ocr" {
  name              = "/aws/lambda/${local.ocr_function_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Project     = "walleza"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role" "ocr_exec" {
  name = "walleza-ocr-exec-${var.environment}"
  # Same trust policy shape as `lambda_exec`/`scheduler_exec`, mirrored
  # rather than shared, per design D45's IAM capability-separation rationale
  # — this role must never be the same resource as either of the other two.
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json

  tags = {
    Project     = "walleza"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_iam_role_policy_attachment" "ocr_basic_execution" {
  role       = aws_iam_role.ocr_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Least-privilege inline policy (design D135): exactly three statements.
# No `s3:PutObject`/`s3:DeleteObject`, no `s3:ListBucket` — this function
# only READS the triggering photo and writes to Postgres directly (design
# D127), it never mutates S3.
data "aws_iam_policy_document" "ocr_least_privilege" {
  statement {
    sid    = "TextractAnalyzeExpense"
    effect = "Allow"
    # Textract exposes no resource-level ARN for AnalyzeExpense — this is an
    # AWS constraint, not laxness (design D135); the action itself is the
    # whole grant.
    actions   = ["textract:AnalyzeExpense"]
    resources = ["*"]
  }

  statement {
    sid       = "ReadOwnReceiptsOnly"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.receipts.arn}/workspaces/*"]
  }

  statement {
    sid       = "ReadDatabaseUrlSecret"
    effect    = "Allow"
    actions   = ["ssm:GetParameter", "ssm:GetParameters"]
    resources = [aws_ssm_parameter.secret["database_url"].arn]
  }

  statement {
    sid       = "DecryptWithDefaultSsmKey"
    effect    = "Allow"
    actions   = ["kms:Decrypt"]
    resources = ["arn:aws:kms:${var.aws_region}:${data.aws_caller_identity.current.account_id}:alias/aws/ssm"]
  }
}

resource "aws_iam_role_policy" "ocr_least_privilege" {
  name   = "ocr-least-privilege"
  role   = aws_iam_role.ocr_exec.id
  policy = data.aws_iam_policy_document.ocr_least_privilege.json
}

resource "aws_lambda_function" "ocr" {
  function_name = local.ocr_function_name
  role          = aws_iam_role.ocr_exec.arn

  # Same zip as the backend/scheduler functions (mirrors both) —
  # first-create-only payload, replaced on every real deploy by the third
  # `aws lambda update-function-code` call added to `.github/workflows/
  # ci-cd.yml`'s existing "Update Lambda function code" step.
  filename         = var.lambda_package_path
  source_code_hash = filebase64sha256(var.lambda_package_path)

  handler       = "app.ocr_worker.handler"
  runtime       = "python3.13"
  architectures = ["arm64"]
  memory_size   = var.lambda_memory_size_mb
  # 60s (design D129): worst case is 4s of in-process backoff plus 3
  # Textract calls plus cold start — well under the scheduler's 300s and
  # the HTTP function's `var.lambda_timeout_seconds`.
  timeout = 60

  environment {
    variables = local.ocr_env
  }

  tags = {
    Project     = "walleza"
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  depends_on = [
    aws_iam_role_policy_attachment.ocr_basic_execution,
    aws_cloudwatch_log_group.ocr,
  ]

  lifecycle {
    # Same rationale as the other two functions: CI/CD owns the deployed
    # code payload after the first apply, and a plain `terraform apply`
    # must not fight that.
    ignore_changes = [
      filename,
      source_code_hash,
      environment,
    ]
  }
}

# Async invocation retries are disabled (design D129) — the handler's own
# in-process Textract retry/backoff (design D128) already owns the terminal
# state, and Lambda's own async retry on top would double-retry
# unpredictably while the handler has no way to know which attempt number
# it's on.
resource "aws_lambda_function_event_invoke_config" "ocr" {
  function_name          = aws_lambda_function.ocr.function_name
  maximum_retry_attempts = 0
}

# S3 validates it can invoke the function at PUT time; without this the
# first apply of `aws_s3_bucket_notification.receipts` below fails with
# "Unable to validate the following destination configurations". The
# permission must exist BEFORE the notification (see its `depends_on`).
#
# `source_account` (in addition to `source_arn`) closes the cross-account
# confused-deputy hole a bucket-ARN-only condition leaves open, since S3
# bucket names are globally unique but the ARN itself is not
# account-qualified (design D135).
resource "aws_lambda_permission" "ocr_from_s3" {
  statement_id   = "AllowInvokeFromReceiptsBucket"
  action         = "lambda:InvokeFunction"
  function_name  = aws_lambda_function.ocr.function_name
  principal      = "s3.amazonaws.com"
  source_arn     = aws_s3_bucket.receipts.arn
  source_account = data.aws_caller_identity.current.account_id
}

# ============================================================================
# SOLE AUTHORITY for `aws_s3_bucket.receipts`' notification configuration
# (design D136). `aws_s3_bucket_notification` maps to
# `PutBucketNotificationConfiguration`, which REPLACES the bucket's ENTIRE
# notification config on every apply.
#
# EXACTLY ONE `aws_s3_bucket_notification` resource may EVER exist for
# `aws_s3_bucket.receipts`, for the lifetime of this project. Any FUTURE
# notification (a second Lambda, an SQS fanout, an SNS topic) MUST be added
# as an additional `lambda_function {}` / `queue {}` / `topic {}` block
# INSIDE THIS SAME RESOURCE — never as a second `aws_s3_bucket_notification`
# resource. A second resource pointed at this bucket would produce two
# Terraform resources each believing it owns the whole config, and they
# would silently clobber each other in nondeterministic order on every
# apply.
#
# See this file's header comment for the MANDATORY pre-apply operator check
# that must be run before the first ever apply of this resource.
# ============================================================================
resource "aws_s3_bucket_notification" "receipts" {
  bucket = aws_s3_bucket.receipts.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.ocr.arn
    # `s3:ObjectCreated:*`, NOT just `:Put` — this app's upload flow uses a
    # presigned POST (design D25), which emits an `ObjectCreated:Post`
    # event, not `:Put`. Filtering to `:Put` alone would mean the Lambda
    # never triggers, which would look exactly like a broken worker with no
    # error anywhere.
    events        = ["s3:ObjectCreated:*"]
    filter_prefix = "workspaces/"
    filter_suffix = "/receipt"
  }

  depends_on = [aws_lambda_permission.ocr_from_s3]
}
