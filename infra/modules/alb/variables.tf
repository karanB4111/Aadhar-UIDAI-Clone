variable "name" {
  description = "Short name for the ALB, target group and SG. ALB name is suffixed."
  type        = string
}

variable "vpc_id" {
  type = string
}

variable "lb_subnet_ids" {
  description = "Subnet IDs for the ALB (one per AZ)."
  type        = list(string)
}

variable "target_port" {
  description = "Port the targets listen on."
  type        = number
  default     = 8000
}

variable "hc_path" {
  description = "ALB health-check path. /health is shallow (ARCHITECTURE.md 5.1.4)."
  type        = string
  default     = "/health"
}

variable "hc_interval" {
  description = "Seconds between health checks (AWS min 5, default 30)."
  type        = number
  default     = 5
}

variable "hc_timeout" {
  description = "Health-check timeout (AWS min 2)."
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
  description = "Target-group deregistration delay in seconds."
  type        = number
  default     = 15
}
