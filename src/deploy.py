"""Build and deploy the API without putting secrets in command arguments or artifacts."""

import argparse
import os
import subprocess
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from .groupings import COLLECTION


PROJECT = Path(__file__).resolve().parents[1]


def deploy(test: bool, region: str):
    stack_name = "aiorganize-api-test" if test else "aiorganize-api"
    secret_name = "TEST_APP_SIGNING_SECRET" if test else "APP_SIGNING_SECRET"
    values = {
        "QdrantEndpoint": os.environ.get("QDRANT_ENDPOINT", ""),
        "QdrantApiKey": os.environ.get("QDRANT_API_KEY", ""),
        "AppSigningSecret": os.environ.get(secret_name, ""),
        "QdrantCollection": f"{COLLECTION}_test" if test else COLLECTION,
    }
    if not all(values.values()) or len(values["AppSigningSecret"]) < 32:
        raise ValueError(f"Configure QDRANT_ENDPOINT, QDRANT_API_KEY, and {secret_name} before deploying.")

    session = boto3.Session(region_name=region)
    account = session.client("sts").get_caller_identity()["Account"]
    bucket = f"aiorganize-deploy-{account}-{region}"
    storage = session.client("s3")

    try:
        storage.head_bucket(Bucket=bucket)
    except ClientError as error:
        if error.response["Error"]["Code"] != "404":
            raise

        configuration = {}
        if region != "us-east-1":
            configuration["CreateBucketConfiguration"] = {"LocationConstraint": region}
        storage.create_bucket(Bucket=bucket, **configuration)

    storage.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    })
    storage.put_bucket_encryption(Bucket=bucket, ServerSideEncryptionConfiguration={
        "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}],
    })

    environment = {**os.environ, "SAM_CLI_TELEMETRY": "0"}
    subprocess.run(["sam", "build", "--region", region], cwd=PROJECT, env=environment, check=True)
    packaged = PROJECT / "dist" / "backend-template.yaml"
    packaged.parent.mkdir(exist_ok=True)
    subprocess.run([
        "sam", "package", "--region", region, "--s3-bucket", bucket,
        "--output-template-file", str(packaged),
    ], cwd=PROJECT, env=environment, check=True)

    cloudformation = session.client("cloudformation")
    try:
        cloudformation.describe_stacks(StackName=stack_name)
        exists = True
    except ClientError as error:
        if error.response["Error"]["Code"] != "ValidationError":
            raise
        exists = False

    parameters = [{"ParameterKey": key, "ParameterValue": value} for key, value in values.items()]
    # Updating code must not rotate every installation's credential accidentally.
    if exists:
        parameters = [item for item in parameters if item["ParameterKey"] != "AppSigningSecret"]
        parameters.append({"ParameterKey": "AppSigningSecret", "UsePreviousValue": True})

    arguments = {
        "StackName": stack_name,
        "TemplateBody": packaged.read_text(),
        "Parameters": parameters,
        "Capabilities": ["CAPABILITY_IAM", "CAPABILITY_AUTO_EXPAND"],
    }
    print(f"Deploying {stack_name} in {region}…", flush=True)
    try:
        if exists:
            cloudformation.update_stack(**arguments)
            waiter = "stack_update_complete"
        else:
            cloudformation.create_stack(**arguments)
            waiter = "stack_create_complete"
        cloudformation.get_waiter(waiter).wait(
            StackName=stack_name, WaiterConfig={"Delay": 5, "MaxAttempts": 180},
        )
    except ClientError as error:
        if error.response["Error"]["Message"] != "No updates are to be performed.":
            raise

    outputs = cloudformation.describe_stacks(StackName=stack_name)["Stacks"][0]["Outputs"]
    for output in outputs:
        if output["OutputKey"] in {"ApiUrl", "AccessTableName"}:
            print(f"{output['OutputKey']}: {output['OutputValue']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="Deploy the separate test API and collection")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()
    deploy(args.test, args.region)


if __name__ == "__main__":
    main()
