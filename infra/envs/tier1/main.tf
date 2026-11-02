# Tier 1 in ap-south-1: VPC + ALB + two static EC2 instances across AZs
# a and b (PLAN step 6). Scope matches ARCHITECTURE.md 5.2 and the PLAN
# row's "Done when": `terraform apply` gives a working ALB URL.

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "aadhaar-ha-demo"
      Tier      = "tier1"
      Owner     = "jeel"
      ManagedBy = "terraform"
    }
  }
}

module "network" {
  source           = "../../modules/network"
  name             = var.name_prefix
  vpc_cidr         = var.vpc_cidr
  azs              = var.azs
  lb_subnet_cidrs  = var.lb_subnet_cidrs
  app_subnet_cidrs = var.app_subnet_cidrs
}

module "alb" {
  source        = "../../modules/alb"
  name          = var.name_prefix
  vpc_id        = module.network.vpc_id
  lb_subnet_ids = module.network.lb_subnet_ids
  # Explicit AWS defaults (ARCHITECTURE.md 5.2); Terraform's differ.
  # Values come from variables so step 7 E1b can swap them to AWS defaults
  # by overriding tfvars rather than editing this file.
  hc_path                = "/health"
  hc_interval            = var.hc_interval
  hc_timeout             = var.hc_timeout
  hc_healthy_threshold   = var.hc_healthy_threshold
  hc_unhealthy_threshold = var.hc_unhealthy_threshold
  deregistration_delay   = var.deregistration_delay
}

module "app" {
  source             = "../../modules/app_static"
  name               = var.name_prefix
  region             = var.region
  app_subnet_ids     = module.network.app_subnet_ids
  azs                = var.azs
  app_sg_id          = module.alb.app_sg_id
  target_group_arn   = module.alb.target_group_arn
  ecr_repository_arn = var.ecr_repository_arn
  ecr_repository_url = var.ecr_repository_url
  image_tag          = var.image_tag
  sign_work          = var.sign_work
}

module "observability" {
  source                  = "../../modules/observability"
  name                    = var.name_prefix
  alarm_email             = var.alarm_email
  alb_arn_suffix          = module.alb.alb_arn_suffix
  target_group_arn_suffix = module.alb.target_group_arn_suffix
  healthy_host_min        = length(var.azs)
}
