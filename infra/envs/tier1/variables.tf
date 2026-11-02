variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "name_prefix" {
  description = "Prefix for Name tags across the stack."
  type        = string
  default     = "aadhaar-tier1"
}

variable "azs" {
  description = "Two Mumbai AZs for Tier 1 (ARCHITECTURE.md 5.2)."
  type        = list(string)
  default     = ["ap-south-1a", "ap-south-1b"]
}

variable "vpc_cidr" {
  type    = string
  default = "10.10.0.0/16"
}

variable "lb_subnet_cidrs" {
  type    = list(string)
  default = ["10.10.0.0/24", "10.10.1.0/24"]
}

variable "app_subnet_cidrs" {
  type    = list(string)
  default = ["10.10.10.0/24", "10.10.11.0/24"]
}

variable "ecr_repository_arn" {
  description = "ARN of the aadhaar-mock ECR repo (output of global/ecr)."
  type        = string
}

variable "ecr_repository_url" {
  description = "URL of the aadhaar-mock ECR repo (output of global/ecr)."
  type        = string
}

variable "image_tag" {
  description = "Short git SHA of the service image pushed to ECR."
  type        = string
}

variable "sign_work" {
  type    = number
  default = 1000
}

variable "alarm_email" {
  description = "Email for SNS alarm notifications. Empty skips the subscription."
  type        = string
  default     = ""
}

# Health-check settings. Defaults match ARCHITECTURE.md 5.2 (fast detection,
# 5-10 s expected error window). E1b overrides these with AWS defaults
# (interval 30, timeout 5, healthy 5, unhealthy 2) to measure the slower band.
variable "hc_interval" {
  description = "ALB target-group health-check interval, seconds."
  type        = number
  default     = 5
}

variable "hc_timeout" {
  description = "ALB target-group health-check timeout, seconds."
  type        = number
  default     = 2
}

variable "hc_healthy_threshold" {
  type    = number
  default = 2
}

variable "hc_unhealthy_threshold" {
  type    = number
  default = 2
}

variable "deregistration_delay" {
  description = "Target-group deregistration delay, seconds."
  type        = number
  default     = 15
}
