output "alb_arn" {
  value = aws_lb.this.arn
}

output "alb_arn_suffix" {
  description = "The ALB ARN suffix used in CloudWatch dimensions."
  value       = aws_lb.this.arn_suffix
}

output "alb_dns_name" {
  description = "DNS name to curl once the stack is up."
  value       = aws_lb.this.dns_name
}

output "alb_zone_id" {
  value = aws_lb.this.zone_id
}

output "target_group_arn" {
  value = aws_lb_target_group.this.arn
}

output "target_group_arn_suffix" {
  value = aws_lb_target_group.this.arn_suffix
}

output "alb_sg_id" {
  value = aws_security_group.alb.id
}

output "app_sg_id" {
  description = "App security group. Attach to EC2 instances in the app module."
  value       = aws_security_group.app_ref.id
}
