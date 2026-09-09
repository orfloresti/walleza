# S3 bucket for receipt-photo attachments (Phase 2 — Categories & Manual
# Transactions, tasks 5.1-5.4). See `sdd/phase-2-categories-transactions`
# design decisions D23-D27 (deterministic object key, presigned-POST upload,
# presigned-GET download, DB-first-then-S3 delete ordering) and D31 (bucket
# name transport — a plain Terraform output, not an SSM parameter, because
# the bucket name is not a secret: it is in the host of every presigned URL
# the browser receives).
#
# Access is ONLY ever via a presigned URL the backend issues after its own
# `visible_transactions` authorization check (design D24) — this bucket is
# never public and the Lambda's IAM policy (see lambda.tf) never grants
# `s3:ListBucket`, so a leaked presigned URL cannot be escalated into a
# bucket listing.
#
# `data.aws_caller_identity.current` is already declared in lambda.tf and
# reused here (a data source is declared once per module, not once per file).

resource "aws_s3_bucket" "receipts" {
  # S3 bucket names are globally unique across all AWS accounts, so the
  # account id is appended to keep this project's `/walleza/<environment>/...`
  # naming spirit without a real collision risk.
  bucket = "walleza-receipts-${var.environment}-${data.aws_caller_identity.current.account_id}"

  # Deliberately false: a rollback (`terraform destroy -target=...`) must not
  # be able to silently delete real uploaded receipts. An operator emptying
  # the bucket by hand before destroying it is the intended friction.
  force_destroy = false

  tags = {
    Project     = "walleza"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# Block all four public-access vectors. This bucket must never be reachable
# except through a presigned URL minted by the backend after authorization
# (design D24) — there is no product reason for any object or bucket policy
# to ever be public.
resource "aws_s3_bucket_public_access_block" "receipts" {
  bucket = aws_s3_bucket.receipts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# ACLs disabled entirely (current AWS best practice, and this project has no
# use case that needs them — every object is written and read by the same
# Lambda execution role via presigned URLs it signs itself).
resource "aws_s3_bucket_ownership_controls" "receipts" {
  bucket = aws_s3_bucket.receipts.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# SSE-S3 (AES256), not a customer-managed KMS key: Phase 0 provisioned no
# CMK, and a CMK would additionally require `kms:GenerateDataKey` on the
# Lambda execution role and KMS-specific headers/conditions in the presigned
# POST policy (design D25) — an unreviewed scope increase for no stated
# requirement.
resource "aws_s3_bucket_server_side_encryption_configuration" "receipts" {
  bucket = aws_s3_bucket.receipts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Disabled, not enabled: design D23 makes a re-upload overwrite the same
# deterministic key in place, and a "deleted" receipt (design D27) must
# actually be gone rather than surviving as a hidden prior version.
resource "aws_s3_bucket_versioning" "receipts" {
  bucket = aws_s3_bucket.receipts.id

  versioning_configuration {
    status = "Disabled"
  }
}

# Housekeeping only — a presigned POST upload that never completes (design
# D25) can leave an incomplete multipart part behind; abort it after 7 days
# so it stops accruing storage cost. Not related to any product retention
# policy.
resource "aws_s3_bucket_lifecycle_configuration" "receipts" {
  bucket = aws_s3_bucket.receipts.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    # Required by the provider even for a bucket-wide rule (empty = every
    # object) — omitting it is deprecated and will be a hard error in a
    # future provider version.
    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# CORS for the browser-to-S3 upload/download flow (design D24/D25/D26).
# `POST` is required because the upload flow uses a presigned POST policy,
# not a presigned PUT (design D25 — a PUT cannot bound size or exact
# Content-Type at S3 itself). `GET`/`HEAD` support the presigned-GET download
# (design D26) and a `fetch`-and-blob render of it in the browser.
resource "aws_s3_bucket_cors_configuration" "receipts" {
  bucket = aws_s3_bucket.receipts.id

  cors_rule {
    allowed_methods = ["POST", "GET", "HEAD"]
    allowed_origins = [var.web_origin]
    allowed_headers = ["content-type"]
    max_age_seconds = 3000
  }
}
