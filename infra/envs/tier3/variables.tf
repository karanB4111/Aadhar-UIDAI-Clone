variable "name_prefix_mumbai" {
  type    = string
  default = "aadhaar-tier3-mu"
}

variable "name_prefix_hyderabad" {
  type    = string
  default = "aadhaar-tier3-hy"
}

variable "mumbai_region" {
  type    = string
  default = "ap-south-1"
}

variable "hyderabad_region" {
  type    = string
  default = "ap-south-2"
}

# Two AZs per region (ARCHITECTURE.md 5.4, 5.3.1): fits the default 5-vCPU
# per-region quota (2 x t3.micro = 4 vCPUs). No quota increase requested (D9).
variable "mumbai_azs" {
  type    = list(string)
  default = ["ap-south-1a", "ap-south-1b"]
}

variable "hyderabad_azs" {
  type    = list(string)
  default = ["ap-south-2a", "ap-south-2b"]
}

# Non-overlapping /16s so the regions could be peered later (ARCHITECTURE.md
# 6.1). 10.10 is Tier 1, 10.11 is Tier 2, 10.20/10.21 are Tier 3.
variable "mumbai_vpc_cidr" {
  type    = string
  default = "10.20.0.0/16"
}

variable "mumbai_lb_subnet_cidrs" {
  type    = list(string)
  default = ["10.20.0.0/24", "10.20.1.0/24"]
}

variable "mumbai_app_subnet_cidrs" {
  type    = list(string)
  default = ["10.20.10.0/24", "10.20.11.0/24"]
}

variable "hyderabad_vpc_cidr" {
  type    = string
  default = "10.21.0.0/16"
}

variable "hyderabad_lb_subnet_cidrs" {
  type    = list(string)
  default = ["10.21.0.0/24", "10.21.1.0/24"]
}

variable "hyderabad_app_subnet_cidrs" {
  type    = list(string)
  default = ["10.21.10.0/24", "10.21.11.0/24"]
}

# ECR repo ARN/URL per region. Mumbai is the source; Hyderabad is the replica
# created by infra/global/ecr. Both hold the same images under the same name
# (ARCHITECTURE.md 5.1.3). The ARN is region-scoped so the app role in each
# region has a least-privilege policy pointing at its own regional repo.
variable "ecr_repository_arn_mumbai" {
  description = "ARN of the aadhaar-mock repo in ap-south-1 (output of global/ecr)."
  type        = string
}

variable "ecr_repository_url_mumbai" {
  description = "URL of the aadhaar-mock repo in ap-south-1 (output of global/ecr)."
  type        = string
}

variable "ecr_repository_arn_hyderabad" {
  description = "ARN of the replicated aadhaar-mock repo in ap-south-2."
  type        = string
}

variable "ecr_repository_url_hyderabad" {
  description = "URL of the replicated aadhaar-mock repo in ap-south-2."
  type        = string
}

variable "image_tag" {
  description = "Short git SHA of the service image. Must exist in both regional ECR repos (replication takes up to 30 min: ARCHITECTURE.md 5.1.3)."
  type        = string
}

variable "sign_work" {
  description = "PBKDF2 iterations per signature. Locked at 4500 after step 9's E0 calibration (PLAN.md section 6)."
  type        = number
  default     = 4500
}

variable "alarm_email" {
  description = "Email for SNS alarm notifications in both regions. Empty skips the subscription."
  type        = string
  default     = ""
}

# Fast health-check settings (ARCHITECTURE.md 5.2), same in both regions.
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

# ASG sizing, same in both regions (ARCHITECTURE.md 5.4). Each region fits the
# default 5-vCPU quota at 2 x t3.micro = 4 vCPUs.
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

# Target-tracking policy target value (requests/target/minute). Step 9 E0
# showed R_max is laptop-bounded at ~160 rps, so leave at Tier 2's value;
# E6a/E6b use the 20 req/s prober where this doesn't trigger.
variable "scaling_target_requests_per_minute" {
  type    = number
  default = 3000
}
