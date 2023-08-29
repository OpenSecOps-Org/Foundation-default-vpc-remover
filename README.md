# Default VPC Remover

The default VPC created for a new account behaves slightly differently from user-created VPCs: amongst other things, their security groups are fully open. Therefore, we must remove all default VPCs in all regions for a newly created account.

This lambda, deployed in the main organisation account in your main region, is triggered by the "new account SNS" topic. It runs in the org account, then assumes the OrganizationAccountAccessRole in the new account to do its work.

NB: The lambda can also be triggered manually. If you provide it with input data of the form:

```
{"AccountId": "123456789012"}
```

the account with the given ID will be processed. If you, on the other hand, provide it with the following data:

```
{"AccountId": "ALL"}
```

then all organisation accounts will be processed. This is useful during initial setup.


## Deployment

First log in to your AWS organisation using SSO and a profile that gives you
AWSAdministratorAccess to the AWS Organizations admin account.

```console
aws sso login --profile <profile-name>
```

Then type:

```console
./deploy-all
```
