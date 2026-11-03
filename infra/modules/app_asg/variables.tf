variable "name" {
  description = "Short name used for the launch template, ASG, instance role/profile and scaling policy."
  type        = string
}

variable "region" {
  description = "AWS region, passed to the container as REGION."
  type        = string
}

variable "app_subnet_ids" {
  description = "App subnet IDs; ASG spreads instances across these (one AZ per subnet)."
  type        = list(string)
}

variable "app_sg_id" {
  description = "App security group id from modules/alb (ALB -> app:8000 chain)."
  type        = string
}

variable "target_group_arn" {
  description = "ALB target group the ASG attaches to."
  type        = string
}

variable "ecr_repository_arn" {
  description = "ARN of the ECR repo used in the instance role's inline policy."
  type        = string
}

variable "ecr_repository_url" {
  description = "ECR repository URL (used by user data for docker login/pull)."
  type        = string
}

variable "image_tag" {
  description = "Image tag to pull. Set to the short git SHA of the service image."
  type        = string
}

variable "instance_type" {
  type    = string
  default = "t3.micro"
}

variable "sign_work" {
  description = "PBKDF2 iterations per signature (service FR7)."
  type        = number
  default     = 1000
}

variable "app_version" {
  description = "Overrides APP_VERSION in the container; defaults to image_tag."
  type        = string
  default     = ""
}

# ASG sizing. Default to min 1 / desired 2 / max 2 (ARCHITECTURE.md 5.3): fits
# the free-account 5-vCPU per-region quota (2 x t3.micro = 4 vCPUs) and shows
# the 1 -> 2 scaling transition for E5.
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

# Health check and warm-up timings (ARCHITECTURE.md 4.3, 5.3). AWS API defaults
# differ from Terraform's; set them explicitly.
variable "health_check_grace_period" {
  description = "ASG health-check grace period in seconds (AWS default 0, Terraform default 300)."
  type        = number
  default     = 180
}

variable "default_instance_warmup" {
  description = "Seconds a new instance is excluded from aggregate metrics after launch."
  type        = number
  default     = 120
}

# Target-tracking scaling policy on ALBRequestCountPerTarget. Expressed as
# requests per target per minute. Default of 3000 assumes R_max = 100/s and a
# 50% target (ARCHITECTURE.md 3.4, 5.3.2); step 9 (E0) retunes it after
# calibration.
variable "scaling_target_requests_per_minute" {
  description = "Target value for ALBRequestCountPerTarget (requests/target/min)."
  type        = number
  default     = 3000
}

variable "scale_in_cooldown" {
  type    = number
  default = 300
}

variable "scale_out_cooldown" {
  type    = number
  default = 60
}

variable "alb_arn_suffix" {
  description = "ALB arn_suffix, used to build the ResourceLabel for ALBRequestCountPerTarget."
  type        = string
}

variable "target_group_arn_suffix" {
  description = "Target group arn_suffix, used to build the ResourceLabel for ALBRequestCountPerTarget."
  type        = string
}
