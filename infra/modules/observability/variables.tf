variable "name" {
  description = "Short name used in alarm names and the SNS topic."
  type        = string
}

variable "alarm_email" {
  description = "Email address subscribed to the SNS topic. Leave empty to skip the subscription."
  type        = string
  default     = ""
}

variable "alb_arn_suffix" {
  description = "arn_suffix of the ALB (CloudWatch dimension)."
  type        = string
}

variable "target_group_arn_suffix" {
  description = "arn_suffix of the ALB target group (CloudWatch dimension)."
  type        = string
}

variable "healthy_host_min" {
  description = "Alarm fires when HealthyHostCount drops below this value."
  type        = number
  default     = 2
}
