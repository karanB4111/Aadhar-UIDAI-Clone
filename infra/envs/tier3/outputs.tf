output "mumbai_alb_url" {
  description = "Open this to confirm Mumbai is live. Primary target for the prober."
  value       = "http://${module.alb_mumbai.alb_dns_name}"
}

output "mumbai_alb_dns_name" {
  value = module.alb_mumbai.alb_dns_name
}

output "mumbai_asg_name" {
  description = "Used by E6b to set desired capacity to 0 (unplanned region loss simulation)."
  value       = module.app_mumbai.asg_name
}

output "mumbai_sns_topic_arn" {
  value = module.observability_mumbai.sns_topic_arn
}

output "hyderabad_alb_url" {
  description = "Open this to confirm Hyderabad is live. Secondary target for the prober."
  value       = "http://${module.alb_hyderabad.alb_dns_name}"
}

output "hyderabad_alb_dns_name" {
  value = module.alb_hyderabad.alb_dns_name
}

output "hyderabad_asg_name" {
  value = module.app_hyderabad.asg_name
}

output "hyderabad_sns_topic_arn" {
  value = module.observability_hyderabad.sns_topic_arn
}

output "prober_urls" {
  description = "Comma-separated primary,secondary URLs for tests/prober.py --urls."
  value       = "http://${module.alb_mumbai.alb_dns_name},http://${module.alb_hyderabad.alb_dns_name}"
}
