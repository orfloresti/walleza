# SES domain identity + DKIM + sandbox recipient identities, and the IAM
# policy granting the scheduler function permission to send reminder email
# (design D52/D53, tasks 4.1/4.2).
#
# Per-environment domain (var.ses_domain: "staging.orfloresti.dev" for
# staging, "orfloresti.dev" for production) — deliberately NOT one shared
# identity across environments, because this module is applied twice into
# the SAME AWS account/region and two applies declaring the same domain
# identity would contend for one global SES resource across two
# independent Terraform states (design D52).
#
# Deliberately NO `aws_ses_domain_mail_from` resource: the default
# amazonses.com MAIL FROM is still DKIM-aligned for DMARC, so skipping it
# avoids one more manual DNS step (an MX + SPF TXT record, plus a
# `BehaviorOnMXFailure` decision) for no lost capability (design D52).

resource "aws_ses_domain_identity" "this" {
  domain = var.ses_domain
}

resource "aws_ses_domain_dkim" "this" {
  domain = aws_ses_domain_identity.this.domain
}

# Phase 4 ships SES-sandbox-only (design D52): in the sandbox, RECIPIENTS
# must also be verified identities, not just the sending domain. Each
# address below triggers a real click-the-link verification email that
# only the recipient's own inbox can complete — Terraform cannot finish
# this step.
resource "aws_ses_email_identity" "sandbox" {
  for_each = toset(var.ses_sandbox_verified_recipients)
  email    = each.value
}

# Design D53: `ses:SendEmail`/`ses:SendRawEmail` scoped to ONLY this
# environment's own domain identity, with a `ses:FromAddress` condition
# pinning the exact From address the role may ever send as. This is the
# true ceiling on what the scheduler function's code can do — mirroring
# `lambda_s3_receipts`'s `workspaces/*` prefix scoping discipline
# (infra/lambda.tf).
data "aws_iam_policy_document" "scheduler_ses" {
  statement {
    sid       = "SendReminderEmail"
    effect    = "Allow"
    actions   = ["ses:SendEmail", "ses:SendRawEmail"]
    resources = ["arn:aws:ses:${var.aws_region}:${data.aws_caller_identity.current.account_id}:identity/${var.ses_domain}"]

    condition {
      test     = "StringEquals"
      variable = "ses:FromAddress"
      values   = [var.ses_from_address]
    }
  }
}

# Attached to `aws_iam_role.scheduler_exec` (infra/scheduler.tf) — NEVER to
# `aws_iam_role.lambda_exec`, the public HTTP execution role. Design D45's
# rationale #2 (IAM capability separation) made structural: a bug in any
# public HTTP handler cannot inherit an email-sending capability, because
# the role serving public requests carries no `ses:*` statement at all.
resource "aws_iam_role_policy" "scheduler_ses" {
  name   = "ses-send-reminder"
  role   = aws_iam_role.scheduler_exec.id
  policy = data.aws_iam_policy_document.scheduler_ses.json
}
