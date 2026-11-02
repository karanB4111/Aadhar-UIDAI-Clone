variable "name" {
  description = "Short name used in resource Name tags, e.g. tier1-mumbai."
  type        = string
}

variable "vpc_cidr" {
  description = "VPC CIDR block, e.g. 10.10.0.0/16 for Mumbai."
  type        = string
}

variable "azs" {
  description = "Availability Zones for lb/app subnets (ordered a, b, c)."
  type        = list(string)
}

variable "lb_subnet_cidrs" {
  description = "CIDR per AZ for load-balancer subnets. Must match length of azs."
  type        = list(string)
}

variable "app_subnet_cidrs" {
  description = "CIDR per AZ for app subnets. Must match length of azs."
  type        = list(string)
}
