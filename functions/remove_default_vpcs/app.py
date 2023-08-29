import os
import json
import botocore
import boto3


org_client = boto3.client('organizations')
sts_client = boto3.client('sts')
ec2_client = boto3.client('ec2')

ROLE_TO_ASSUME = os.environ['ROLE_TO_ASSUME']


def lambda_handler(data, _context):
    print("Data: ", data)

    account_id = data['AccountId'].strip('"')
    regions = data['Regions']

    process_account(account_id, regions)

    return True


def process_account(account_id, regions):
    print('==============================================')
    print(f'Processing account {account_id}...')

    # Assume the Role in the other account
    other_acct = sts_client.assume_role(
        RoleArn=f"arn:aws:iam::{account_id}:role/{ROLE_TO_ASSUME}",
        RoleSessionName=f"cross_acct_remove_default_vpcs_{account_id}"
    )

    access_key = other_acct['Credentials']['AccessKeyId']
    secret_key = other_acct['Credentials']['SecretAccessKey']
    session_token = other_acct['Credentials']['SessionToken']

    for region in regions:
        # Create EC2 client for the other account and region
        new_ec2_client = boto3.client(
            'ec2',
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            aws_session_token=session_token,
            region_name=region
        )
        # Ninja assassination
        delete_full_vpc_in_region(new_ec2_client, region, dryrun=False)


#######################################################################
# This is the core logic:
#######################################################################

def delete_igw(ec2, vpc_id, dryrun=False):
    args = {
        'Filters': [
            {
                'Name': 'attachment.vpc-id',
                'Values': [vpc_id]
            }
        ]
    }
    try:
        igw = ec2.describe_internet_gateways(**args)['InternetGateways']
    except botocore.exceptions.ClientError as exc:
        print(exc.response['Error']['Message'])
    if igw:
        igw_id = igw[0]['InternetGatewayId']
        try:
            print("  Detaching ", str(igw_id))
            if not dryrun:
                ec2.detach_internet_gateway(
                    InternetGatewayId=igw_id, VpcId=vpc_id)
        except botocore.exceptions.ClientError as exc:
            print(exc.response['Error']['Message'])
        try:
            print("  Deleting " + str(igw_id))
            if not dryrun:
                ec2.delete_internet_gateway(InternetGatewayId=igw_id)
        except botocore.exceptions.ClientError as exc:
            print(exc.response['Error']['Message'])


def delete_subs(ec2, args, dryrun=False):
    try:
        subs = ec2.describe_subnets(**args)['Subnets']
    except botocore.exceptions.ClientError as exc:
        print(exc.response['Error']['Message'])
    if subs:
        for sub in subs:
            sub_id = sub['SubnetId']
            try:
                print("  Deleting " + str(sub_id))
                if not dryrun:
                    ec2.delete_subnet(SubnetId=sub_id)
            except botocore.exceptions.ClientError as exc:
                print(exc.response['Error']['Message'])


def delete_rtbs(ec2, args, dryrun=False):
    try:
        rtbs = ec2.describe_route_tables(**args)['RouteTables']
    except botocore.exceptions.ClientError as exc:
        print(exc.response['Error']['Message'])
    if rtbs:
        for rtb in rtbs:
            main = 'false'
            for assoc in rtb['Associations']:
                main = assoc['Main']
            if main:
                continue
            rtb_id = rtb['RouteTableId']
            try:
                print("  Deleting " + str(rtb_id))
                if not dryrun:
                    ec2.delete_route_table(RouteTableId=rtb_id)
            except botocore.exceptions.ClientError as exc:
                print(exc.response['Error']['Message'])


def delete_acls(ec2, args, dryrun=False):
    try:
        acls = ec2.describe_network_acls(**args)['NetworkAcls']
    except botocore.exceptions.ClientError as exc:
        print(exc.response['Error']['Message'])
    if acls:
        for acl in acls:
            default = acl['IsDefault']
            if default:
                continue
            acl_id = acl['NetworkAclId']
            try:
                print("  Deleting " + str(acl_id))
                if not dryrun:
                    ec2.delete_network_acl(NetworkAclId=acl_id)
            except botocore.exceptions.ClientError as exc:
                print(exc.response['Error']['Message'])


def delete_sgps(ec2, args, dryrun=False):
    try:
        sgps = ec2.describe_security_groups(**args)['SecurityGroups']
    except botocore.exceptions.ClientError as exc:
        print(exc.response['Error']['Message'])
    if sgps:
        for sgp in sgps:
            default = sgp['GroupName']
            if default == 'default':
                continue
            sg_id = sgp['GroupId']
            try:
                print("  Deleting " + str(sg_id))
                if not dryrun:
                    ec2.delete_security_group(GroupId=sg_id)
            except botocore.exceptions.ClientError as exc:
                print(exc.response['Error']['Message'])


def delete_vpc(ec2, vpc_id, region, dryrun=False):
    try:
        print("  Deleting " + str(vpc_id))
        if not dryrun:
            ec2.delete_vpc(VpcId=vpc_id)
    except botocore.exceptions.ClientError as exc:
        print(exc.response['Error']['Message'])
    else:
        print('VPC {} has been deleted from the {} region.'.format(vpc_id, region))


def get_default_vpcs(ec2):
    vpc_list = []
    try:
        vpcs = ec2.describe_vpcs(
            Filters=[
                {
                    'Name': 'isDefault',
                    'Values': [
                        'true',
                    ],
                },
            ]
        )
    except botocore.exceptions.ClientError as error:
        if error.response['Error']['Code'] == 'OptInRequired':
            print("Opt-in required, skipping.")
            return []
        else:
            raise error

    vpcs_str = json.dumps(vpcs)
    resp = json.loads(vpcs_str)
    data = json.dumps(resp['Vpcs'])
    vpcs = json.loads(data)

    for vpc in vpcs:
        vpc_list.append(vpc['VpcId'])

    return vpc_list


def get_availability_zones(ec2, region):
    result = []
    azs = ec2.describe_availability_zones()['AvailabilityZones']
    for az in azs:
        if az['RegionName'] == region:
            result.append(az['ZoneName'])
    return result


def vpc_has_instances(ec2, region, args):
    avzones = get_availability_zones(ec2, region)
    reservations = ec2.describe_instances(**args)['Reservations']
    for reservation in reservations:
        if 'Instances' in reservation:
            for instance in reservation['Instances']:
                if instance['Placement']['AvailabilityZone'] in avzones:
                    return True
    return False


def delete_full_vpc_in_region(ec2, region, dryrun=False):
    vpcs = get_default_vpcs(ec2)
    if len(vpcs) == 0:
        print(f"No default VPC in {region}")
        return
    if len(vpcs) > 1:
        print(f"Too many default VPCs in {region}: ", vpcs)
        return
    vpc_id = vpcs[0]

    print(f"  {region}: Removing Default VPC {vpc_id}...")

    # Common args to many calls
    args = {
        'Filters': [
            {
                'Name': 'vpc-id',
                'Values': [vpc_id]
            }
        ]
    }

    # Are there any instances?
    try:
        if vpc_has_instances(ec2, region, args):
            print(' VPC {} has existing instances in the {} region. Keeping.'.format(
                vpc_id, region))
            return
    except botocore.exceptions.ClientError as error:
        if error.response['Error']['Code'] == 'OptInRequired':
            print("Opt-in required, skipping.")
            return
        else:
            raise error

    delete_igw(ec2, vpc_id, dryrun)
    delete_subs(ec2, args, dryrun)
    delete_rtbs(ec2, args, dryrun)
    delete_acls(ec2, args, dryrun)
    delete_sgps(ec2, args, dryrun)
    delete_vpc(ec2, vpc_id, region, dryrun)
