output "asg_name" {
  description = "Name of the Auto Scaling group (used by instance-refresh / zonal-shift commands)."
  value       = aws_autoscaling_group.this.name
}

output "asg_arn" {
  value = aws_autoscaling_group.this.arn
}

output "launch_template_id" {
  value = aws_launch_template.this.id
}

output "launch_template_latest_version" {
  value = aws_launch_template.this.latest_version
}

output "instance_role_name" {
  value = aws_iam_role.instance.name
}

output "scaling_policy_arn" {
  value = aws_autoscaling_policy.request_count.arn
}
