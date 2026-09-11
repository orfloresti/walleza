# EventBridge schedule wiring for the scheduler Lambda (design D51, task
# 3.2). One rule per environment, targeting `aws_lambda_function.scheduler`
# (infra/scheduler.tf) — never `aws_lambda_function.backend`.
#
# `aws_cloudwatch_event_rule`/`_target`, not `aws_scheduler_schedule`
# (EventBridge Scheduler): design D51 rejects Scheduler because its only
# real advantage (`schedule_expression_timezone`) is unneeded here — 06:00
# UTC is stably 00:00 in `America/Mexico_City` (no DST since 2022) — and
# Rules use a resource policy, needing no extra IAM role.
#
# No DLQ (`dead_letter_config` deliberately omitted, design D51): the event
# payload is a bare scheduled tick with zero diagnostic information: a DLQ
# would capture empty messages while the real diagnostics are the run's own
# structured CloudWatch log line. One retry (`maximum_retry_attempts = 1`)
# covers a transient pooler blip and is safe because generation's
# idempotency (design D47) makes a retry a no-op; a run that timed out will
# time out again on retry regardless, and tomorrow's run catches up by
# construction (design D48).

resource "aws_cloudwatch_event_rule" "generation" {
  name                = "walleza-generation-${var.environment}"
  description         = "Daily trigger for walleza-scheduler-${var.environment} (occurrence generation + reminders, design D51)."
  schedule_expression = var.generation_schedule_expression

  # Default-disabled (`var.generation_schedule_enabled` defaults to false,
  # variables.tf): the first `terraform apply` per environment must not be
  # able to fire generation before the deployment/migration/smoke-test
  # sequence in the design's Migration/Rollout section completes.
  state = var.generation_schedule_enabled ? "ENABLED" : "DISABLED"

  tags = {
    Project     = "walleza"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_cloudwatch_event_target" "generation" {
  rule      = aws_cloudwatch_event_rule.generation.name
  target_id = "walleza-scheduler-${var.environment}"
  arn       = aws_lambda_function.scheduler.arn

  retry_policy {
    maximum_retry_attempts = 1
    # EventBridge rejects 0 (the Terraform provider's implicit default when
    # this is left unset) — 60s is the API's own minimum. Harmless here: one
    # retry of a once-daily tick well within 60s of the original attempt is
    # exactly the transient-blip case design D51 wants covered.
    maximum_event_age_in_seconds = 60
  }

  # No `dead_letter_config` block — see file header.
}

# Required whenever an EventBridge rule targets a Lambda function: without
# this resource-based policy statement scoped to this exact rule's ARN, the
# rule's invocation is silently rejected. Mirrors
# `aws_lambda_permission.function_url_public` (infra/lambda.tf) in shape,
# but for a completely different principal/source: `events.amazonaws.com`
# scoped to this ONE rule's ARN, never `"*"`.
resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scheduler.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.generation.arn
}
