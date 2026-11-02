# bootstrap/

One-shot stack that creates the S3 bucket all other stacks use as their
Terraform backend (ARCHITECTURE.md section 7). Local state only — this
stack is tiny and runs once per account.

```
cd infra/bootstrap
terraform init
terraform apply
```

Outputs the bucket name, which goes into each env's `backend.tf` (see
`envs/tier1/backend.tf`).

AWS action needed before apply: AWS account exists, root MFA on,
`ap-south-1` enabled, an IAM user for Jeel with Admin and
`~/.aws/credentials` configured (ARCHITECTURE.md 6.4). Nothing else.
