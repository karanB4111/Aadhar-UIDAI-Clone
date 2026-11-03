# Tier 2 in ap-south-1: VPC + ALB + ASG (min 1 / desired 2 / max 2) across
# AZs a and b, with the Tier 1 CloudWatch alarms (PLAN step 8). Scope matches
# ARCHITECTURE.md 5.3 and the PLAN row's "Done when": a killed instance is
# replaced automatically.
#
# Reuses modules/network, modules/alb and modules/observability unchanged;
# swaps modules/app_static for modules/app_asg.

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      Project   = "aadhaar-ha-demo"
      Tier      = "tier2"
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
  source                 = "../../modules/alb"
  name                   = var.name_prefix
  vpc_id                 = module.network.vpc_id
  lb_subnet_ids          = module.network.lb_subnet_ids
  hc_path                = "/health"
  hc_interval            = var.hc_interval
  hc_timeout             = var.hc_timeout
  hc_healthy_threshold   = var.hc_healthy_threshold
  hc_unhealthy_threshold = var.hc_unhealthy_threshold
  deregistration_delay   = var.deregistration_delay
}

module "app" {
  source                             = "../../modules/app_asg"
  name                               = var.name_prefix
  region                             = var.region
  app_subnet_ids                     = module.network.app_subnet_ids
  app_sg_id                          = module.alb.app_sg_id
  target_group_arn                   = module.alb.target_group_arn
  alb_arn_suffix                     = module.alb.alb_arn_suffix
  target_group_arn_suffix            = module.alb.target_group_arn_suffix
  ecr_repository_arn                 = var.ecr_repository_arn
  ecr_repository_url                 = var.ecr_repository_url
  image_tag                          = var.image_tag
  sign_work                          = var.sign_work
  asg_min                            = var.asg_min
  asg_desired                        = var.asg_desired
  asg_max                            = var.asg_max
  scaling_target_requests_per_minute = var.scaling_target_requests_per_minute
}

module "observability" {
  source                  = "../../modules/observability"
  name                    = var.name_prefix
  alarm_email             = var.alarm_email
  alb_arn_suffix          = module.alb.alb_arn_suffix
  target_group_arn_suffix = module.alb.target_group_arn_suffix
  # Alarm fires when fewer than asg_desired targets are healthy. E4 relies
  # on this signal to know when the ASG has brought the replacement in.
  healthy_host_min = var.asg_desired
}
