output "repository_url" {
  description = "ECR repository URL in ap-south-1 (push target)."
  value       = aws_ecr_repository.aadhaar_mock.repository_url
}

output "repository_arn" {
  description = "ARN of the ECR repository (used by instance role policies)."
  value       = aws_ecr_repository.aadhaar_mock.arn
}

output "repository_name" {
  description = "ECR repository name."
  value       = aws_ecr_repository.aadhaar_mock.name
}
