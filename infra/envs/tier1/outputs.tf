output "alb_url" {
  description = "Open this to confirm Tier 1 is live."
  value       = "http://${module.alb.alb_dns_name}"
}

output "alb_dns_name" {
  value = module.alb.alb_dns_name
}

output "instance_ids" {
  value = module.app.instance_ids
}

output "sns_topic_arn" {
  value = module.observability.sns_topic_arn
}
