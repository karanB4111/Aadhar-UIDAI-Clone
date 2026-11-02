# Public ALB with an HTTP:80 listener and one target group on :8000.
# Health-check values are set explicitly: Terraform's defaults differ from
# AWS's (ARCHITECTURE.md 5.2, CONTRIBUTING.md).

resource "aws_security_group" "alb" {
  name        = "${var.name}-alb"
  description = "ALB ingress from the Internet; egress to app targets only."
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name}-alb" }
}

resource "aws_vpc_security_group_ingress_rule" "alb_http" {
  security_group_id = aws_security_group.alb.id
  description       = "HTTP from anywhere (Route 53 health checkers in Tier 3 too)"
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
  cidr_ipv4         = "0.0.0.0/0"
}

# Egress to the app security group is attached from the caller (envs/tier1),
# because the app SG lives in modules/app_static. The caller passes the
# app SG id and we open the egress rule here.
resource "aws_vpc_security_group_egress_rule" "alb_to_app" {
  security_group_id            = aws_security_group.alb.id
  description                  = "To app targets on target_port"
  ip_protocol                  = "tcp"
  from_port                    = var.target_port
  to_port                      = var.target_port
  referenced_security_group_id = aws_security_group.app_ref.id
}

# Placeholder SG that caller replaces via the aws_security_group.app_ref
# data source? No — we create a tiny companion SG so the alb_to_app rule
# can reference it. The app module adds its own ingress from this SG.
resource "aws_security_group" "app_ref" {
  name        = "${var.name}-app"
  description = "App tier; only the ALB may reach port ${var.target_port}."
  vpc_id      = var.vpc_id

  tags = { Name = "${var.name}-app" }
}

resource "aws_vpc_security_group_ingress_rule" "app_from_alb" {
  security_group_id            = aws_security_group.app_ref.id
  description                  = "From ALB on target_port"
  ip_protocol                  = "tcp"
  from_port                    = var.target_port
  to_port                      = var.target_port
  referenced_security_group_id = aws_security_group.alb.id
}

resource "aws_vpc_security_group_egress_rule" "app_https_out" {
  security_group_id = aws_security_group.app_ref.id
  description       = "HTTPS to the Internet for ECR and AL2023 package repos"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_lb" "this" {
  name                       = substr("${var.name}-alb", 0, 32)
  internal                   = false
  load_balancer_type         = "application"
  security_groups            = [aws_security_group.alb.id]
  subnets                    = var.lb_subnet_ids
  drop_invalid_header_fields = true
  idle_timeout               = 60

  tags = { Name = "${var.name}-alb" }
}

resource "aws_lb_target_group" "this" {
  name        = substr("${var.name}-tg", 0, 32)
  port        = var.target_port
  protocol    = "HTTP"
  target_type = "instance"
  vpc_id      = var.vpc_id

  deregistration_delay = var.deregistration_delay
  # Slow start off: the app has no warm-up (ARCHITECTURE.md 5.2).
  slow_start = 0

  health_check {
    enabled             = true
    path                = var.hc_path
    port                = "traffic-port"
    protocol            = "HTTP"
    matcher             = "200"
    interval            = var.hc_interval
    timeout             = var.hc_timeout
    healthy_threshold   = var.hc_healthy_threshold
    unhealthy_threshold = var.hc_unhealthy_threshold
  }

  tags = { Name = "${var.name}-tg" }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.this.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.this.arn
  }
}
