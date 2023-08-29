import os
from random import randint
import json
import boto3
from botocore.exceptions import ClientError

step_client = boto3.client('stepfunctions')

org_client = boto3.client('organizations')
ec2_client = boto3.client('ec2')


STATE_MACHINE_ARN = os.environ['STATE_MACHINE_ARN']


def lambda_handler(event, _context):
    print(event)

    account_ids = []
    regions = get_regions(ec2_client)

    if 'AccountId' in event:
        if event['AccountId'] == 'ALL':
            account_ids = get_all_organization_account_ids()
        else:
            account_ids.append(event['AccountId'])
    else:
        message_raw = event['Records'][0]['Sns']['Message']
        if isinstance(message_raw, str) and message_raw[0] != '{':
            account_id = message_raw
        else:
            message = json.loads(message_raw)
            detail = message.get('detail')
            if detail:
                account_id = detail['serviceEventDetails']['createAccountStatus']['accountId']
            else:
                print("No account details available")
                return True
        account_ids.append(account_id)
    print(f'{len(account_ids)} Account IDs to process: ', account_ids)

    random_number = randint(100000, 999999)
    name = f'remove-default-vpcs-job-{random_number}'

    step_client.start_execution(
        stateMachineArn=STATE_MACHINE_ARN,
        name=name,
        input=json.dumps({
            "AccountIds": account_ids,
            "Regions": regions,
        })
    )

    return True


def get_all_organization_account_ids():
    ids = []
    paginator = org_client.get_paginator('list_accounts')
    page_iterator = paginator.paginate()
    for page in page_iterator:
        for account in page['Accounts']:
            if account['Status'] == 'ACTIVE':
                account_id = account['Id']
                ids.append(account_id)
    return sorted(ids)


def get_regions(ec2):
    regions = []
    try:
        aws_regions = ec2.describe_regions()['Regions']
    except ClientError as exc:
        print(exc.response['Error']['Message'])
    else:
        for region in aws_regions:
            regions.append(region['RegionName'])
    return regions
