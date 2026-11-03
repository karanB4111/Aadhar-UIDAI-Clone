#  Tier 2 app tier: launch template + Auto Scaling group across the app
#  subnets, with a target-tracking policy on ALBRequestCountPerTarget
#  (ARCHITECTURE.md 5.3). Reuses the app security group created by the alb
#  module (same chain as Tier 1).

# AL2023 x86_64 AMI id from the public SSM parameter (ARCHITECTURE.md 7).
data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "${var.name}-instance"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

# SSM Session Manager - no SSH, no key pair (ARCHITECTURE.md 6.4).
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

# Least-privilege ECR pull: GetAuthorizationToken on *, read actions scoped
# to the aadhaar-mock repo only.
data "aws_iam_policy_document" "ecr_pull" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }
  statement {
    sid = "EcrPull"
    actions = [
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchCheckLayerAvailability",
    ]
    resources = [var.ecr_repository_arn]
  }
}

resource "aws_iam_role_policy" "ecr_pull" {
  name   = "${var.name}-ecr-pull"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.ecr_pull.json
}

resource "aws_iam_instance_profile" "instance" {
  name = "${var.name}-instance"
  role = aws_iam_role.instance.name
}

locals {
  app_version  = var.app_version != "" ? var.app_version : var.image_tag
  ecr_registry = split("/", var.ecr_repository_url)[0]
  user_data    = <<-BASH
    #!/bin/bash
    set -euxo pipefail

    # Instance identity, read on the host via IMDSv2 (hop limit 1, container
    # cannot reach IMDS).
    TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" \
      -H "X-aws-ec2-metadata-token-ttl-seconds: 300")
    IID=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
      http://169.254.169.254/latest/meta-data/instance-id)
    AZ=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" \
      http://169.254.169.254/latest/meta-data/placement/availability-zone)

    dnf install -y docker
    systemctl enable --now docker

    dnf install -y awscli
    aws ecr get-login-password --region ${var.region} | \
      docker login --username AWS --password-stdin ${local.ecr_registry}

    docker pull ${var.ecr_repository_url}:${var.image_tag}

    docker run -d --name aadhaar-mock \
      --restart=unless-stopped \
      -p 8000:8000 \
      -e INSTANCE_ID="$IID" \
      -e AZ="$AZ" \
      -e REGION="${var.region}" \
      -e APP_VERSION="${local.app_version}" \
      -e SIGN_WORK="${var.sign_work}" \
      ${var.ecr_repository_url}:${var.image_tag}
  BASH

  # ResourceLabel for the predefined ALBRequestCountPerTarget metric:
  # app/<alb-name>/<alb-id>/targetgroup/<tg-name>/<tg-id>
  alb_resource_label = "${var.alb_arn_suffix}/${var.target_group_arn_suffix}"
}

resource "aws_launch_template" "this" {
  name          = "${var.name}-lt"
  image_id      = data.aws_ssm_parameter.al2023_ami.value
  instance_type = var.instance_type
  user_data     = base64encode(local.user_data)

  iam_instance_profile {
    name = aws_iam_instance_profile.instance.name
  }

  vpc_security_group_ids = [var.app_sg_id]

  # IMDSv2 required, hop limit 1 so the container cannot reach IMDS
  # (ARCHITECTURE.md 6.3).
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    http_endpoint               = "enabled"
  }

  # Unlimited credits (ARCHITECTURE.md 5.1.2). Set here so an account-level
  # default cannot change it.
  credit_specification {
    cpu_credits = "unlimited"
  }

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_type = "gp3"
      volume_size = 8
      encrypted   = true
    }
  }

  # Tag the instances the ASG launches (default_tags cover the launch
  # template itself but not the instances it spawns).
  tag_specifications {
    resource_type = "instance"
    tags = {
      Name = "${var.name}-asg"
    }
  }

  tag_specifications {
    resource_type = "volume"
    tags = {
      Name = "${var.name}-asg"
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_autoscaling_group" "this" {
  name                = "${var.name}-asg"
  vpc_zone_identifier = var.app_subnet_ids

  min_size         = var.asg_min
  desired_capacity = var.asg_desired
  max_size         = var.asg_max

  # ELB health checks: replace instances whose /health fails
  # (ARCHITECTURE.md 5.1.4).
  health_check_type         = "ELB"
  health_check_grace_period = var.health_check_grace_period
  default_instance_warmup   = var.default_instance_warmup

  target_group_arns = [var.target_group_arn]

  # Pin the launch template to a numbered version so instance refresh can
  # roll back (ARCHITECTURE.md 5.3, note on $Latest).
  launch_template {
    id      = aws_launch_template.this.id
    version = aws_launch_template.this.latest_version
  }

  # Launch before terminating during replacements and instance refresh.
  instance_maintenance_policy {
    min_healthy_percentage = 100
    max_healthy_percentage = 150
  }

  # Enable the group metrics used in the Tier 2 timeline charts (free,
  # 1-minute granularity).
  enabled_metrics = [
    "GroupMinSize",
    "GroupMaxSize",
    "GroupDesiredCapacity",
    "GroupInServiceInstances",
    "GroupPendingInstances",
    "GroupStandbyInstances",
    "GroupTerminatingInstances",
    "GroupTotalInstances",
  ]

  tag {
    key                 = "Name"
    value               = "${var.name}-asg"
    propagate_at_launch = true
  }

  # Do not tie the ASG lifecycle to the launch template's $Latest; a change
  # to desired_capacity from the scaling policy should not force a replace.
  lifecycle {
    ignore_changes = [desired_capacity]
  }
}

# Target-tracking policy on ALBRequestCountPerTarget. The ALB publishes this
# metric every 60 s whenever there is traffic (ARCHITECTURE.md 5.3.2).
resource "aws_autoscaling_policy" "request_count" {
  name                   = "${var.name}-tt-reqcount"
  autoscaling_group_name = aws_autoscaling_group.this.name
  policy_type            = "TargetTrackingScaling"

  target_tracking_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ALBRequestCountPerTarget"
      resource_label         = local.alb_resource_label
    }
    target_value     = var.scaling_target_requests_per_minute
    disable_scale_in = false
  }

  estimated_instance_warmup = var.default_instance_warmup
}
