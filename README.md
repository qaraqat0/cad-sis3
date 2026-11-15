# SIS 3: Reproducible container + messaging stack (CloudFormation)

Everything is defined as code. The console is only used for looking.

## Architecture

```
Client ──HTTP──▶ ALB ──▶ ECS Fargate service (2 tasks, ARM64, image from ECR)
                              │  POST /orders  (task role: sns:Publish only)
                              ▼
                     SNS topic  "OrderCreated" (domain event)
                              │  raw message delivery
                              ▼
                     SQS queue ──(after 5 receives)──▶ DLQ (14 days)
                              │
                              ▼
                     Lambda consumer (idempotent)
                              │  conditional PutItem on eventId
                              ▼
                     DynamoDB "processed-events"
```

| Stack | Template | Contents |
|---|---|---|
| `<p>-network` | `templates/network.yaml` | VPC, 2 public subnets in 2 AZs, IGW, route table, ALB SG, task SG |
| `<p>-messaging` | `templates/messaging.yaml` | SNS topic, SQS queue + DLQ (maxReceiveCount 5), Lambda consumer, DynamoDB dedup table, log group |
| `<p>-ecr` | `templates/ecr.yaml` | ECR repo: immutable tags, scan on push, lifecycle policy (keep last 5) |
| `<p>-app` | `templates/app.yaml` | ALB, target group (ip), ECS cluster, task definition, service, execution role, task role, log group |

Stacks are linked by **CloudFormation exports** prefixed with the project name, so a second copy never collides with the first.

## Requirements → where they are

| Requirement | Where |
|---|---|
| SQS queue with DLQ and maxReceiveCount | `messaging.yaml` → `OrdersQueue.RedrivePolicy` |
| Domain event through SNS | `OrdersTopic`, published by the app on `POST /orders` |
| Idempotent consumer, deduplication key | `eventId`; `ConditionExpression: attribute_not_exists(eventId)` |
| ECR: immutable tags, lifecycle policy | `ecr.yaml` |
| ECS Fargate behind ALB, two separate roles | `app.yaml` → `ExecutionRole` (pull image, write logs) and `TaskRole` (only `sns:Publish` on our topic) |
| Logs in CloudWatch with retention | `/ecs/<p>-app` and `/aws/lambda/<p>-consumer`, 7 days |
| Parameters for the environment | `ProjectName`, `Environment`, `ImageTag`, `DesiredCount`, `LogRetentionDays` |
| No secrets in the template | none. The task gets AWS access through its IAM role, not keys |

## Deploy (one command)

Prerequisites: AWS CLI v2 logged in, Docker running, region `us-east-1`.

```bash
./deploy.sh            # project name "sis3"
```

The script deploys the network, messaging and ECR stacks, builds and pushes the image tagged with the git commit, then deploys the app stack. It prints the app URL at the end.

### Reproducibility test (second copy)

```bash
git clone <repo-url> sis3-clean && cd sis3-clean
./deploy.sh sis3-copy
```

## Smoke test

```bash
URL=$(aws cloudformation describe-stacks --stack-name sis3-app \
  --query "Stacks[0].Outputs[?OutputKey=='AppUrl'].OutputValue" --output text)

curl $URL/                                  # which task answered
curl -X POST "$URL/orders"                  # new event
curl -X POST "$URL/orders?id=order-42"      # fixed eventId
curl -X POST "$URL/orders?id=order-42"      # same id again -> duplicate_skipped

aws logs tail /aws/lambda/sis3-consumer --since 10m
aws dynamodb scan --table-name sis3-processed-events --select COUNT
```

DLQ test (message without `eventId`, fails 5 times, then lands in the DLQ):

```bash
TOPIC=$(aws cloudformation describe-stacks --stack-name sis3-messaging \
  --query "Stacks[0].Outputs[?OutputKey=='TopicArn'].OutputValue" --output text)
aws sns publish --topic-arn $TOPIC --message '{"type":"Broken"}'
# wait about 10 minutes (5 receives x 120 s visibility timeout)
aws sqs get-queue-attributes --queue-url $(aws sqs get-queue-url --queue-name sis3-orders-dlq --query QueueUrl --output text) \
  --attribute-names ApproximateNumberOfMessages
```

## Validate before deploy

```bash
pip install cfn-lint checkov
cfn-lint templates/*.yaml
checkov -d templates --framework cloudformation --quiet
```

## Clean up

```bash
./destroy.sh            # or ./destroy.sh sis3-copy
```

Deletes app → ecr → messaging → network. The ECR repo is emptied automatically (`EmptyOnDelete`).
