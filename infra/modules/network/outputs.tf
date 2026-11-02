output "vpc_id" {
  value = aws_vpc.this.id
}

output "lb_subnet_ids" {
  description = "Load-balancer subnet IDs, in the same order as var.azs."
  value       = aws_subnet.lb[*].id
}

output "app_subnet_ids" {
  description = "App subnet IDs, in the same order as var.azs."
  value       = aws_subnet.app[*].id
}

output "deny_all_nacl_id" {
  description = "Pre-built deny-all NACL for the AZ-loss test."
  value       = aws_network_acl.deny_all.id
}
