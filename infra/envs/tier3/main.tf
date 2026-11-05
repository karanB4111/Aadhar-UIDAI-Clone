# Tier 3: two independent regional stacks (Mumbai + Hyderabad), each Tier-2
# shaped (VPC + ALB + ASG min 1 / desired 2 / max 2 across 2 AZs + alarms).
# PLAN step 11.
#
# Scope note (2026-11-05): O1 (domain) was descoped by the group. Route 53
# latency+health-check routing stays as paper design in ARCHITECTURE.md 5.4
# and is NOT built. E6b measures client-side failover (tests/prober.py
# --urls) which is a documented lower bound on the Route 53 case.
#
# Each region reuses modules/network, modules/alb, modules/app_asg and
# modules/observability unchanged, driven by a region-scoped provider alias.

provider "aws" {
  alias  = "mumbai"
  region = var.mumbai_region
  default_tags {
    tags = {
      Project   = "aadhaar-ha-demo"
      Tier      = "tier3"
      Region    = "mumbai"
      Owner     = "jeel"
      ManagedBy = "terraform"
    }
  }
}

provider "aws" {
  alias  = "hyderabad"
  region = var.hyderabad_region
  default_tags {
    tags = {
      Project   = "aadhaar-ha-demo"
      Tier      = "tier3"
      Region    = "hyderabad"
      Owner     = "jeel"
      ManagedBy = "terraform"
    }
  }
}

# ---- Mumbai ----------------------------------------------------------------

module "network_mumbai" {
  source = "../../modules/network"
  providers = {
    aws = aws.mumbai
  }
  name             = var.name_prefix_mumbai
  vpc_cidr         = var.mumbai_vpc_cidr
  azs              = var.mumbai_azs
  lb_subnet_cidrs  = var.mumbai_lb_subnet_cidrs
  app_subnet_cidrs = var.mumbai_app_subnet_cidrs
}

module "alb_mumbai" {
  source = "../../modules/alb"
  providers = {
    aws = aws.mumbai
  }
  name                   = var.name_prefix_mumbai
  vpc_id                 = module.network_mumbai.vpc_id
  lb_subnet_ids          = module.network_mumbai.lb_subnet_ids
  hc_path                = "/health"
  hc_interval            = var.hc_interval
  hc_timeout             = var.hc_timeout
  hc_healthy_threshold   = var.hc_healthy_threshold
  hc_unhealthy_threshold = var.hc_unhealthy_threshold
  deregistration_delay   = var.deregistration_delay
}

module "app_mumbai" {
  source = "../../modules/app_asg"
  providers = {
    aws = aws.mumbai
  }
  name                               = var.name_prefix_mumbai
  region                             = var.mumbai_region
  app_subnet_ids                     = module.network_mumbai.app_subnet_ids
  app_sg_id                          = module.alb_mumbai.app_sg_id
  target_group_arn                   = module.alb_mumbai.target_group_arn
  alb_arn_suffix                     = module.alb_mumbai.alb_arn_suffix
  target_group_arn_suffix            = module.alb_mumbai.target_group_arn_suffix
  ecr_repository_arn                 = var.ecr_repository_arn_mumbai
  ecr_repository_url                 = var.ecr_repository_url_mumbai
  image_tag                          = var.image_tag
  sign_work                          = var.sign_work
  asg_min                            = var.asg_min
  asg_desired                        = var.asg_desired
  asg_max                            = var.asg_max
  scaling_target_requests_per_minute = var.scaling_target_requests_per_minute
}

module "observability_mumbai" {
  source = "../../modules/observability"
  providers = {
    aws = aws.mumbai
  }
  name                    = var.name_prefix_mumbai
  alarm_email             = var.alarm_email
  alb_arn_suffix          = module.alb_mumbai.alb_arn_suffix
  target_group_arn_suffix = module.alb_mumbai.target_group_arn_suffix
  healthy_host_min        = var.asg_desired
}

# ---- Hyderabad -------------------------------------------------------------

module "network_hyderabad" {
  source = "../../modules/network"
  providers = {
    aws = aws.hyderabad
  }
  name             = var.name_prefix_hyderabad
  vpc_cidr         = var.hyderabad_vpc_cidr
  azs              = var.hyderabad_azs
  lb_subnet_cidrs  = var.hyderabad_lb_subnet_cidrs
  app_subnet_cidrs = var.hyderabad_app_subnet_cidrs
}

module "alb_hyderabad" {
  source = "../../modules/alb"
  providers = {
    aws = aws.hyderabad
  }
  name                   = var.name_prefix_hyderabad
  vpc_id                 = module.network_hyderabad.vpc_id
  lb_subnet_ids          = module.network_hyderabad.lb_subnet_ids
  hc_path                = "/health"
  hc_interval            = var.hc_interval
  hc_timeout             = var.hc_timeout
  hc_healthy_threshold   = var.hc_healthy_threshold
  hc_unhealthy_threshold = var.hc_unhealthy_threshold
  deregistration_delay   = var.deregistration_delay
}

module "app_hyderabad" {
  source = "../../modules/app_asg"
  providers = {
    aws = aws.hyderabad
  }
  name                               = var.name_prefix_hyderabad
  region                             = var.hyderabad_region
  app_subnet_ids                     = module.network_hyderabad.app_subnet_ids
  app_sg_id                          = module.alb_hyderabad.app_sg_id
  target_group_arn                   = module.alb_hyderabad.target_group_arn
  alb_arn_suffix                     = module.alb_hyderabad.alb_arn_suffix
  target_group_arn_suffix            = module.alb_hyderabad.target_group_arn_suffix
  ecr_repository_arn                 = var.ecr_repository_arn_hyderabad
  ecr_repository_url                 = var.ecr_repository_url_hyderabad
  image_tag                          = var.image_tag
  sign_work                          = var.sign_work
  asg_min                            = var.asg_min
  asg_desired                        = var.asg_desired
  asg_max                            = var.asg_max
  scaling_target_requests_per_minute = var.scaling_target_requests_per_minute
}

module "observability_hyderabad" {
  source = "../../modules/observability"
  providers = {
    aws = aws.hyderabad
  }
  name                    = var.name_prefix_hyderabad
  alarm_email             = var.alarm_email
  alb_arn_suffix          = module.alb_hyderabad.alb_arn_suffix
  target_group_arn_suffix = module.alb_hyderabad.target_group_arn_suffix
  healthy_host_min        = var.asg_desired
}
