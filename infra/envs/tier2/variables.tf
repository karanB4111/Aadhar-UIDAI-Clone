variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "name_prefix" {
  description = "Prefix for Name tags across the stack."
  type        = string
  default     = "aadhaar-tier2"
}

variable "azs" {
  description = "Two Mumbai AZs for Tier 2 (ARCHITECTURE.md 5.3, 5.3.1)."
  type        = list(string)
  default     = ["ap-south-1a", "ap-south-1b"]
}

# A separate /16 so Tier 1 and Tier 2 can coexist for one review session
# without clashing.
variable "vpc_cidr" {
  type    = string
  default = "10.11.0.0/16"
}

variable "lb_subnet_cidrs" {
  type    = list(string)
  default = ["10.11.0.0/24", "10.11.1.0/24"]
}

variable "app_subnet_cidrs" {
  type    = list(string)
  default = ["10.11.10.0/24", "10.11.11.0/24"]
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

# Fast health-check settings (ARCHITECTURE.md 5.2). Variables so step 9 or a
# follow-up can swap them without editing main.tf.
variable "hc_interval" {
  type    = number
  default = 5
}

variable "hc_timeout" {
  type    = number
  default = 2
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
  type    = number
  default = 15
}

# ASG sizing (ARCHITECTURE.md 5.3): fits the default 5-vCPU per-region quota
# (2 x t3.micro = 4 vCPUs). No quota increase is requested (D9).
variable "asg_min" {
  type    = number
  default = 1
}

variable "asg_desired" {
  type    = number
  default = 2
}

variable "asg_max" {
  type    = number
  default = 2
}

# Target-tracking policy target value, requests per target per minute. Default
# of 3000 assumes R_max = 100 req/s and a 50% target (ARCHITECTURE.md 3.4,
# 5.3.2). Step 9 retunes it after E0 calibration.
variable "scaling_target_requests_per_minute" {
  type    = number
  default = 3000
}
