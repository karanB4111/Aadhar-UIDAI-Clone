output "alb_url" {
  description = "Open this to confirm Tier 2 is live."
  value       = "http://${module.alb.alb_dns_name}"
}

output "alb_dns_name" {
  value = module.alb.alb_dns_name
}

output "asg_name" {
  description = "ASG name, used by step 9 and E4 commands (terminate / instance-refresh)."
  value       = module.app.asg_name
}

output "launch_template_id" {
  value = module.app.launch_template_id
}

output "scaling_policy_arn" {
  value = module.app.scaling_policy_arn
}

output "sns_topic_arn" {
  value = module.observability.sns_topic_arn
}
