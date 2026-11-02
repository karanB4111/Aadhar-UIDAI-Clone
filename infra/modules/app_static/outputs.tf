output "instance_ids" {
  description = "EC2 instance ids, in the same order as app_subnet_ids."
  value       = aws_instance.app[*].id
}

output "instance_public_ips" {
  description = "Public IPv4 of each instance (useful for SSM Session Manager fallback and debugging)."
  value       = aws_instance.app[*].public_ip
}

output "instance_role_name" {
  value = aws_iam_role.instance.name
}
