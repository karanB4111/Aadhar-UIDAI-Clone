# Long-lived: the ECR repository that holds the aadhaar-mock image for every
# tier. Immutable tags (short git SHA) and replication to ap-south-2 so Tier 3
# can pull without re-pushing (ARCHITECTURE.md 5.1.3). This stack stays up
# between sessions and is destroyed only in step 12.

provider "aws" {
  region = "ap-south-1"
  default_tags {
    tags = {
      Project   = "aadhaar-ha-demo"
      Tier      = "shared"
      Owner     = "jeel"
      ManagedBy = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

resource "aws_ecr_repository" "aadhaar_mock" {
  name                 = var.repository_name
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }
}

# Keep storage small on a free account: only the last 10 image versions
# per tag prefix.
resource "aws_ecr_lifecycle_policy" "aadhaar_mock" {
  repository = aws_ecr_repository.aadhaar_mock.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# Replicate every push in ap-south-1 to ap-south-2 for Tier 3. Replication
# only applies to images pushed after this rule exists (ARCHITECTURE.md
# 5.1.3), so push the image at least 30 min before Tier 3 tests, or push
# directly to both regions.
resource "aws_ecr_replication_configuration" "mumbai_to_hyderabad" {
  replication_configuration {
    rule {
      destination {
        region      = "ap-south-2"
        registry_id = data.aws_caller_identity.current.account_id
      }
    }
  }
}
