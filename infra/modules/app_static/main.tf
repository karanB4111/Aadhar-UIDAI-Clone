# Tier 1: two standalone EC2 instances (ARCHITECTURE.md 5.2), one per app
# subnet, each registered with the ALB target group. No ASG here — self-
# healing is step 8 (modules/app_asg).

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

# SSM Session Manager — no SSH, no key pair (ARCHITECTURE.md 6.4).
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
  app_version    = var.app_version != "" ? var.app_version : var.image_tag
  ecr_registry   = split("/", var.ecr_repository_url)[0]
  user_data_tmpl = <<-BASH
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

    # ECR login
    dnf install -y awscli
    aws ecr get-login-password --region ${var.region} | \
      docker login --username AWS --password-stdin ${local.ecr_registry}

    docker pull ${var.ecr_repository_url}:${var.image_tag}

    # Run the service. For E1 we need the process to stay down when
    # stopped, so --restart=no.
    docker run -d --name aadhaar-mock \
      --restart=no \
      -p 8000:8000 \
      -e INSTANCE_ID="$IID" \
      -e AZ="$AZ" \
      -e REGION="${var.region}" \
      -e APP_VERSION="${local.app_version}" \
      -e SIGN_WORK="${var.sign_work}" \
      ${var.ecr_repository_url}:${var.image_tag}
  BASH
}

resource "aws_instance" "app" {
  count                       = length(var.app_subnet_ids)
  ami                         = data.aws_ssm_parameter.al2023_ami.value
  instance_type               = var.instance_type
  subnet_id                   = var.app_subnet_ids[count.index]
  vpc_security_group_ids      = [var.app_sg_id]
  iam_instance_profile        = aws_iam_instance_profile.instance.name
  user_data                   = local.user_data_tmpl
  user_data_replace_on_change = true

  # IMDSv2 required, hop limit 1 so the container cannot reach IMDS
  # (ARCHITECTURE.md 6.3).
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 1
    http_endpoint               = "enabled"
  }

  # Unlimited credits (ARCHITECTURE.md 5.1.2).
  credit_specification {
    cpu_credits = "unlimited"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 8
    encrypted   = true
  }

  tags = {
    Name = "${var.name}-${substr(var.azs[count.index], -1, 1)}"
    AZ   = var.azs[count.index]
  }
}

resource "aws_lb_target_group_attachment" "app" {
  count            = length(aws_instance.app)
  target_group_arn = var.target_group_arn
  target_id        = aws_instance.app[count.index].id
  port             = 8000
}
