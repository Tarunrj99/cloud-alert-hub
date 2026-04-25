# AWS Lambda — SNS → cloud_alert_hub

Four files, same pattern as the GCP example.

```
examples/aws-lambda/
├── lambda_function.py   <-- 10 lines; imports cloud_alert_hub
├── requirements.txt     <-- pip install from your public repo
├── config.yaml          <-- your overrides
└── deploy.sh            <-- package + deploy + SNS subscribe
```

## 1. One-time AWS setup

* An SNS topic your alert sources publish to (AWS Budgets, CloudWatch alarms,
  EventBridge rules, Security Hub findings, etc.).
* A Lambda execution role with `AWSLambdaBasicExecutionRole` attached.
* An S3 bucket for persistent dedup state (a few KB):

  ```bash
  export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
  aws s3 mb "s3://${ACCOUNT_ID}-alert-hub-state" --region us-east-1
  ```

  Then attach this inline policy to the Lambda's execution role so it can
  read and write its dedup state:

  ```json
  {
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::ACCOUNT_ID-alert-hub-state/dedup-state.json"
    }]
  }
  ```

  Without persistent state, Lambda cold starts (every ~5–15 min idle) wipe
  the dedup map and AWS Budgets re-emissions re-fire suppressed alerts.

## 2. Point `requirements.txt` at your fork

Replace `Tarunrj99/cloud-alert-hub` with your own public repo path.
Pin to a tag (`@v0.3.3`) or commit SHA for reproducible deploys.

The shipped requirements line uses the `[aws]` extra
(`cloud-alert-hub[aws] @ git+…`) which pulls in `boto3` for the S3 dedup
backend.

## 3. Edit `config.yaml`

Enable only the features this Lambda should handle. For separation of duties,
deploy the same code a second time with a security-only or SLO-only config.

## 4. Deploy

```bash
export ROLE_ARN=arn:aws:iam::123456789012:role/cloud-alert-hub-lambda
export SNS_TOPIC_ARN=arn:aws:sns:us-east-1:123456789012:alerts
export SLACK_WEBHOOK_URL=https://hooks.slack.com/...
./deploy.sh
```

## Producer examples

* **AWS Budgets** → Budget actions → SNS topic `alerts`.
* **CloudWatch Alarms** → alarm action → SNS topic `alerts`.
* **EventBridge** → rule with `source = aws.securityhub` → SNS target.

Every message lands at `lambda_function.lambda_handler`, which hands it to
`cloud_alert_hub`. The `kind` field picks the feature; if none matches, the event
is suppressed with `reason: no_feature_claimed` (visible in CloudWatch Logs).
