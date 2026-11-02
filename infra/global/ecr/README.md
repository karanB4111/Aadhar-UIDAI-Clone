# global/ecr/

ECR repository `aadhaar-mock` in `ap-south-1` with immutable tags and a
replication rule to `ap-south-2` (ARCHITECTURE.md 5.1.3). Long-lived; kept
up between sessions. Destroyed only in step 12.

```
cd infra/global/ecr
terraform init -backend-config=backend.tfvars
terraform apply
```

AWS action needed first: `ap-south-2` opt-in enabled in the account
(ARCHITECTURE.md 5.4.5, risk R2). Without it, the replication rule applies
but copies never arrive.

After apply, push the current service image:

```
TAG=$(git rev-parse --short HEAD)
REPO=$(terraform output -raw repository_url)
aws ecr get-login-password --region ap-south-1 | \
  docker login --username AWS --password-stdin "${REPO%/*}"
cd ../../../service
docker buildx build --platform linux/amd64 --load -t "$REPO:$TAG" .
docker push "$REPO:$TAG"
```
