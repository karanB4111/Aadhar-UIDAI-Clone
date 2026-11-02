variable "name" {
  description = "Short name for the instance role/profile and the Name tag."
  type        = string
}

variable "region" {
  description = "AWS region, passed to the container as REGION."
  type        = string
}

variable "app_subnet_ids" {
  description = "App subnet IDs, in the same order as azs. One instance per subnet."
  type        = list(string)
}

variable "azs" {
  description = "AZ names, in the same order as app_subnet_ids."
  type        = list(string)
}

variable "app_sg_id" {
  description = "App security group id from modules/alb."
  type        = string
}

variable "target_group_arn" {
  description = "ALB target group to register each instance with."
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
