# VPC with one public route table shared by lb-* and app-* subnets in each
# AZ, plus a spare "deny-all" network ACL used by the AZ-loss test
# (ARCHITECTURE.md 6.1, 8.6). App subnets map a public IPv4 so instances
# can reach ECR and AL2023 package repos without a NAT gateway; the
# security group chain in modules/alb and modules/app_static still blocks
# inbound traffic that is not from the ALB.

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = var.name }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = var.name }
}

resource "aws_subnet" "lb" {
  count                   = length(var.azs)
  vpc_id                  = aws_vpc.this.id
  availability_zone       = var.azs[count.index]
  cidr_block              = var.lb_subnet_cidrs[count.index]
  map_public_ip_on_launch = false

  tags = {
    Name = "${var.name}-lb-${substr(var.azs[count.index], -1, 1)}"
    Role = "lb"
  }
}

resource "aws_subnet" "app" {
  count                   = length(var.azs)
  vpc_id                  = aws_vpc.this.id
  availability_zone       = var.azs[count.index]
  cidr_block              = var.app_subnet_cidrs[count.index]
  map_public_ip_on_launch = true

  tags = {
    Name = "${var.name}-app-${substr(var.azs[count.index], -1, 1)}"
    Role = "app"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = { Name = "${var.name}-public" }
}

resource "aws_route_table_association" "lb" {
  count          = length(var.azs)
  subnet_id      = aws_subnet.lb[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "app" {
  count          = length(var.azs)
  subnet_id      = aws_subnet.app[count.index].id
  route_table_id = aws_route_table.public.id
}

# Deny-all NACL, attached to nothing. The AZ-loss test (E3, E6b) temporarily
# associates it with an app subnet to simulate loss of that AZ.
resource "aws_network_acl" "deny_all" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name}-deny-all" }
}

resource "aws_network_acl_rule" "deny_all_ingress" {
  network_acl_id = aws_network_acl.deny_all.id
  rule_number    = 100
  egress         = false
  protocol       = "-1"
  rule_action    = "deny"
  cidr_block     = "0.0.0.0/0"
}

resource "aws_network_acl_rule" "deny_all_egress" {
  network_acl_id = aws_network_acl.deny_all.id
  rule_number    = 100
  egress         = true
  protocol       = "-1"
  rule_action    = "deny"
  cidr_block     = "0.0.0.0/0"
}
