#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Build a zip deployment package and (optionally) create the Lambda.
# Requires AWS CLI v2, Python 3.10+, and an existing execution role.
# ---------------------------------------------------------------------------
set -euo pipefail

FUNCTION_NAME="${FUNCTION_NAME:-cloud-alert-hub}"
ROLE_ARN="${ROLE_ARN:?set ROLE_ARN env var (Lambda execution role)}"
SNS_TOPIC_ARN="${SNS_TOPIC_ARN:?set SNS_TOPIC_ARN env var}"
SLACK_WEBHOOK_URL="${SLACK_WEBHOOK_URL:?set SLACK_WEBHOOK_URL env var}"
RUNTIME="${RUNTIME:-python3.12}"
REGION="${AWS_REGION:-us-east-1}"

WORKDIR="$(mktemp -d)"
cp lambda_function.py config.yaml "$WORKDIR/"
pip install --quiet --target "$WORKDIR" -r requirements.txt

pushd "$WORKDIR" >/dev/null
zip -q -r /tmp/cloud-alert-hub-lambda.zip .
popd >/dev/null

if aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" >/dev/null 2>&1; then
  echo "==> Updating existing function $FUNCTION_NAME"
  aws lambda update-function-code \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --zip-file fileb:///tmp/cloud-alert-hub-lambda.zip >/dev/null
else
  echo "==> Creating function $FUNCTION_NAME"
  aws lambda create-function \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --runtime "$RUNTIME" \
    --role "$ROLE_ARN" \
    --handler lambda_function.lambda_handler \
    --timeout 30 \
    --memory-size 256 \
    --zip-file fileb:///tmp/cloud-alert-hub-lambda.zip \
    --environment "Variables={SLACK_WEBHOOK_URL=${SLACK_WEBHOOK_URL}}" >/dev/null
fi

echo "==> Subscribing function to $SNS_TOPIC_ARN"
LAMBDA_ARN="$(aws lambda get-function --function-name "$FUNCTION_NAME" --region "$REGION" --query 'Configuration.FunctionArn' --output text)"
aws sns subscribe --region "$REGION" --topic-arn "$SNS_TOPIC_ARN" --protocol lambda --notification-endpoint "$LAMBDA_ARN" >/dev/null || true
aws lambda add-permission --region "$REGION" --function-name "$FUNCTION_NAME" \
  --statement-id "sns-$(date +%s)" --action lambda:InvokeFunction \
  --principal sns.amazonaws.com --source-arn "$SNS_TOPIC_ARN" >/dev/null 2>&1 || true

echo "==> Done. Publish a test message:"
echo "    aws sns publish --topic-arn $SNS_TOPIC_ARN --message '{\"kind\":\"budget\",\"title\":\"demo\",\"summary\":\"hi\"}'"
