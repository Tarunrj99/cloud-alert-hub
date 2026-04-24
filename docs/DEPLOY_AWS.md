# Deploying on AWS

The recommended runtime is an **SNS-triggered Lambda**. The example lives in
[`examples/aws-lambda/`](../examples/aws-lambda/); this doc walks it through.

> **Before you start** — read the [Requirements](../README.md#requirements)
> section of the top-level README. You need AWS CLI v2, Python 3.10+, and a
> Slack webhook URL.

## Prerequisites

| Item | How to check / fix |
| ---- | ------------------ |
| AWS CLI v2 installed and logged in | `aws sts get-caller-identity` |
| An AWS account you can deploy to | the above returns an account ID |
| Deployer identity has the permissions below | `aws iam simulate-principal-policy …` or trust the console |
| A Lambda execution role you can pass | `AWSLambdaBasicExecutionRole` attached |
| An SNS topic for alert sources | we'll create one in the next step if needed |
| Public GitHub fork of this repo | Lambda packaging `pip install`s from there |
| Slack incoming webhook URL | <https://api.slack.com/messaging/webhooks> |

**Required IAM permissions** on the deployer identity:

- `lambda:CreateFunction`, `lambda:UpdateFunctionCode`,
  `lambda:UpdateFunctionConfiguration`, `lambda:AddPermission`,
  `lambda:GetFunction`
- `iam:PassRole` (for the Lambda execution role)
- `sns:CreateTopic`, `sns:Subscribe`, `sns:Publish` (publish is only needed
  for the smoke test)
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`
  (on the Lambda execution role, not the deployer)

## 0. Create the SNS topic and execution role (one-time)

```bash
export AWS_REGION=us-east-1

# SNS topic the producers (Budgets, CloudWatch, EventBridge…) will publish to
aws sns create-topic --region "$AWS_REGION" --name alerts

# Minimum execution role the Lambda assumes at runtime
aws iam create-role --role-name cloud-alert-hub-lambda \
  --assume-role-policy-document '{
    "Version":"2012-10-17",
    "Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]
  }'

aws iam attach-role-policy --role-name cloud-alert-hub-lambda \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

Capture the two ARNs you'll need below:

```bash
export SNS_TOPIC_ARN=$(aws sns create-topic --region "$AWS_REGION" --name alerts --query TopicArn --output text)
export ROLE_ARN=$(aws iam get-role --role-name cloud-alert-hub-lambda --query Role.Arn --output text)
```

## 1. Copy the example

```bash
cp -r examples/aws-lambda ~/my-lambda-alerting
cd ~/my-lambda-alerting
```

## 2. Point `requirements.txt` at your fork

```
git+https://github.com/Tarunrj99/cloud-alert-hub.git@v0.3.1#egg=cloud-alert-hub
```

## 3. Edit `config.yaml`

Pick which features this Lambda handles. Set `routing.routes.*.slack_channel`
to real channel names and — if email is on — add recipients.

## 4. Deploy

```bash
export ROLE_ARN=arn:aws:iam::123456789012:role/cloud-alert-hub-lambda
export SNS_TOPIC_ARN=arn:aws:sns:us-east-1:123456789012:alerts
export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/XXX/YYY/ZZZ
export FUNCTION_NAME=cloud-alert-hub
chmod +x deploy.sh && ./deploy.sh
```

`deploy.sh` packages `lambda_function.py`, `config.yaml`, and the pip-
installed `cloud_alert_hub` into a zip, then either creates or updates the
function and subscribes it to SNS.

## 5. Smoke test

```bash
aws sns publish --topic-arn "$SNS_TOPIC_ARN" --message='{
  "kind": "budget",
  "severity": "high",
  "title": "Smoke test 100%",
  "summary": "AWS budget alert from CLI.",
  "account_id": "123456789012",
  "labels": {"budget_name": "demo", "threshold_percent": "100"}
}'
```

Check CloudWatch Logs for the function and your Slack channel.

## 6. Wire real producers

| Source | How |
| ------ | --- |
| **AWS Budgets** | Budget → actions → SNS topic |
| **CloudWatch alarms** | alarm action → SNS topic |
| **EventBridge rules** | rule target → SNS topic (e.g. Security Hub findings) |
| **GuardDuty / Security Hub** | EventBridge rule → SNS topic |

The function is cloud-agnostic — every source just needs to publish JSON
that matches the canonical schema (or a schema your producer fills in).

## 7. Package size note

`cloud_alert_hub` and its dependencies comfortably fit inside the Lambda 50 MB
zip limit (pydantic + httpx + pyyaml ≈ 15 MB unzipped). If you add heavy
integrations, consider promoting `cloud_alert_hub` to a **Lambda Layer** so
multiple functions share it.

## Troubleshooting

| Symptom | Likely cause | Fix |
| ------- | ------------ | --- |
| Deploy fails with `ResourceConflictException` | Function already exists | `deploy.sh` handles update-vs-create based on `get-function`; re-run |
| `AccessDeniedException: iam:PassRole` | Deployer can't pass the execution role | Attach `iam:PassRole` on the role's ARN to your deployer identity |
| Function runs but nothing in Slack | `SLACK_WEBHOOK_URL` env var missing | `aws lambda get-function-configuration --function-name $FUNCTION_NAME` |
| SNS → Lambda plumbing not wired | `AddPermission` step skipped | Re-run `deploy.sh`; it's idempotent |
| Events always suppressed | Payload `kind` doesn't match any enabled feature | Enable `app.debug_mode: true`; CloudWatch Logs will include `debug.trace` with the reason |
| Zip > 50 MB | Heavy extras pulled in | Move `cloud_alert_hub` into a Lambda Layer; only ship the thin wrapper + `config.yaml` |

## Next steps

- Turn on more features (SLO, security, infra) → [`FEATURES.md`](FEATURES.md).
- Audit / debug a running deployment → [`DEBUG_RUNBOOK.md`](DEBUG_RUNBOOK.md).
- Tune config for production → [`CONFIGURATION.md`](CONFIGURATION.md).
- Deploying to GCP too? → [`DEPLOY_GCP.md`](DEPLOY_GCP.md).
