output "lambda_function_url" {
  description = "Public Function URL for the backend Lambda. Wire this into frontend/wrangler.toml's per-environment API_ORIGIN var (see that file's header comment) — never expose it to the browser directly (design D9)."
  value       = aws_lambda_function_url.backend.function_url
}

output "lambda_function_arn" {
  description = "ARN of the backend Lambda function."
  value       = aws_lambda_function.backend.arn
}

output "lambda_function_name" {
  description = "Name of the backend Lambda function, used by ci-cd.yml's deploy job (WALLEZA_ENVIRONMENT-derived, `walleza-backend-<environment>`)."
  value       = aws_lambda_function.backend.function_name
}

output "github_actions_deploy_role_arn" {
  description = "ARN to set as this GitHub Environment's AWS_DEPLOY_ROLE_ARN variable (Settings > Environments > <environment> > Variables), consumed by ci-cd.yml's `role-to-assume` input."
  value       = aws_iam_role.github_actions_deploy.arn
}

output "github_oidc_provider_arn" {
  description = "ARN of the account-wide GitHub Actions OIDC provider (created once — see variables.tf's create_github_oidc_provider doc)."
  value       = local.github_oidc_provider_arn
}

output "ssm_parameter_names" {
  description = "Full names of every SecureString parameter this environment expects a real value written into out of band (see ssm.tf's file header for the `aws ssm put-parameter --overwrite` command)."
  value       = { for k, v in aws_ssm_parameter.secret : k => v.name }
}

output "receipts_bucket_name" {
  description = "Name of the S3 bucket storing receipt-photo attachments (Phase 2 categories & transactions). Needed for the manual `aws lambda update-function-configuration` fix on an already-existing function — see README.md's \"S3 Receipts Bucket\" section — since lambda.tf's `ignore_changes=[environment]` blocks WALLEZA_S3_RECEIPTS_BUCKET from reaching it via a plain apply."
  value       = aws_s3_bucket.receipts.bucket
}

output "receipts_bucket_arn" {
  description = "ARN of the S3 receipts bucket."
  value       = aws_s3_bucket.receipts.arn
}

output "scheduler_function_name" {
  description = "Name of the scheduler Lambda function (walleza-scheduler-<environment>), used by ci-cd.yml's deploy job's second `aws lambda update-function-code` call and by the manual smoke-test invoke (`aws lambda invoke --function-name <this>`)."
  value       = aws_lambda_function.scheduler.function_name
}
