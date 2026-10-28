"""
remove_default_vpcs: throttling and other transient AWS errors leave the Lambda as AWSTransientError, which
the state machine retries (a rerun re-describes what is left). A delete that fails for another reason, e.g.
a dependency, is logged and the removal continues. A describe that fails for another reason fails the
Lambda with its own error; nothing can be deleted without it.
"""

from unittest.mock import MagicMock, patch

import botocore.exceptions
import pytest

from aws_errors import AWSTransientError
from functions.remove_default_vpcs import app

REGION = 'eu-north-1'


def client_error(code, status=400):
    return botocore.exceptions.ClientError(
        {'Error': {'Code': code, 'Message': code}, 'ResponseMetadata': {'HTTPStatusCode': status}}, 'op')


THROTTLE = ('RequestLimitExceeded', 503)


def default_vpc_ec2():
    ec2 = MagicMock(name='ec2')
    ec2.describe_vpcs.return_value = {'Vpcs': [{'VpcId': 'vpc-1'}]}
    ec2.describe_availability_zones.return_value = {'AvailabilityZones': [{'RegionName': REGION,
                                                                          'ZoneName': f'{REGION}a'}]}
    ec2.describe_instances.return_value = {'Reservations': []}
    ec2.describe_internet_gateways.return_value = {'InternetGateways': [{'InternetGatewayId': 'igw-1'}]}
    ec2.describe_subnets.return_value = {'Subnets': [{'SubnetId': 'subnet-1'}]}
    ec2.describe_route_tables.return_value = {'RouteTables': []}
    ec2.describe_network_acls.return_value = {'NetworkAcls': []}
    ec2.describe_security_groups.return_value = {'SecurityGroups': []}
    return ec2


def run(ec2):
    sts = MagicMock()
    sts.assume_role.return_value = {'Credentials': {'AccessKeyId': 'a', 'SecretAccessKey': 'b',
                                                    'SessionToken': 'c'}}
    with patch.object(app, 'sts_client', sts), patch.object(app.boto3, 'client', return_value=ec2):
        return app.lambda_handler({'AccountId': '111111111111', 'Regions': [REGION]}, None)


def test_removes_the_default_vpc():
    ec2 = default_vpc_ec2()
    assert run(ec2) is True
    ec2.delete_internet_gateway.assert_called_once_with(InternetGatewayId='igw-1')
    ec2.delete_subnet.assert_called_once_with(SubnetId='subnet-1')
    ec2.delete_vpc.assert_called_once_with(VpcId='vpc-1')


@pytest.mark.parametrize('call', ['describe_vpcs', 'describe_instances', 'describe_internet_gateways',
                                  'describe_subnets', 'describe_route_tables', 'describe_network_acls',
                                  'describe_security_groups'])
def test_a_throttled_describe_is_retried(call):
    ec2 = default_vpc_ec2()
    getattr(ec2, call).side_effect = client_error(*THROTTLE)
    with pytest.raises(AWSTransientError):
        run(ec2)


@pytest.mark.parametrize('call', ['detach_internet_gateway', 'delete_internet_gateway', 'delete_subnet',
                                  'delete_vpc'])
def test_a_throttled_delete_is_retried(call):
    ec2 = default_vpc_ec2()
    getattr(ec2, call).side_effect = client_error(*THROTTLE)
    with pytest.raises(AWSTransientError):
        run(ec2)


def test_a_throttled_role_assumption_is_retried():
    sts = MagicMock()
    sts.assume_role.side_effect = client_error('Throttling')
    with patch.object(app, 'sts_client', sts):
        with pytest.raises(AWSTransientError):
            app.lambda_handler({'AccountId': '111111111111', 'Regions': [REGION]}, None)


def test_a_delete_refused_for_another_reason_is_logged_and_the_removal_continues(capsys):
    ec2 = default_vpc_ec2()
    ec2.delete_subnet.side_effect = client_error('DependencyViolation')
    assert run(ec2) is True
    ec2.delete_vpc.assert_called_once_with(VpcId='vpc-1')
    assert 'DependencyViolation' in capsys.readouterr().out


@pytest.mark.parametrize('call', ['describe_internet_gateways', 'describe_subnets', 'describe_route_tables',
                                  'describe_network_acls', 'describe_security_groups'])
def test_a_describe_refused_for_another_reason_fails_with_its_own_error(call):
    ec2 = default_vpc_ec2()
    getattr(ec2, call).side_effect = client_error('UnauthorizedOperation', 403)
    with pytest.raises(botocore.exceptions.ClientError) as raised:
        run(ec2)
    assert raised.value.response['Error']['Code'] == 'UnauthorizedOperation'
    ec2.delete_vpc.assert_not_called()


def test_a_region_that_is_not_opted_in_is_skipped():
    ec2 = default_vpc_ec2()
    ec2.describe_vpcs.side_effect = client_error('OptInRequired', 401)
    assert run(ec2) is True
    ec2.delete_vpc.assert_not_called()
