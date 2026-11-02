output "state_bucket" {
  description = "S3 bucket name that every env stack uses as its backend."
  value       = aws_s3_bucket.tfstate.id
}

output "state_bucket_region" {
  description = "Region of the state bucket."
  value       = var.region
}
