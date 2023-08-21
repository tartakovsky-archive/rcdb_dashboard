## Supported exchanges

### binance
Supported accounts types: `Spot` `Cross Margin` `Isolated Margin` `USDT-M Futures` `COIN-M Futures`

### ascendex
Supported accounts types: `Spot` `Cross Margin` `USDT-M Futures`

### kucoin
Supported accounts types: `Main` `Spot` `Cross Margin` `USDT-M Futures` `COIN-M Futures`
> **Futures API has individual credentials. Create a separeted account for future types!**<br>e.g `user_main_fut` for USDT-M Futures, COIN-M Futures and `user_main` for others types

## Example `.env`
```
DATASTORE_URL=http://172.31.46.70
DATASTORE_TOKEN=token

AWS_DEFAULT_REGION=ap-northeast-1
DOCKER_REGISTRY=807440325307.dkr.ecr.ap-northeast-1.amazonaws.com
SENTRY_DSN=http://dsn@172.31.0.13/2
CREDENTIALSTORE_URL=http://172.31.13.68
CREDENTIALSTORE_TOKEN=token
CREDENTIALSTORE_VAULT=prod-secrets
BINANCE_PROXIES=http://login:password@193.23.253.109:7681,...
SLACK_TOKEN=token
SLACK_CHANNEL=chanel-id
```

## Initial setup

### Required AWS policies

- Policy for the EC2 instance for CloudWatch logs:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Action": [
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "logs:CreateLogGroup"
            ],
            "Effect": "Allow",
            "Resource": "*"
        }
    ]
}
```
- Policy for the ci/cd user for image push/pull to/from ECR:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "VisualEditor0",
            "Effect": "Allow",
            "Action": "ecr:GetAuthorizationToken",
            "Resource": "*"
        }
    ]
}
```
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "wtf",
            "Effect": "Allow",
            "Resource": "*",
            "Action": [
                "ecr:GetDownloadUrlForLayer",
                "ecr:PutImage",
                "ecr:InitiateLayerUpload",
                "ecr:UploadLayerPart",
                "ecr:CompleteLayerUpload",
                "ecr:DescribeRepositories",
                "ecr:GetRepositoryPolicy",
                "ecr:ListImages",
                "ecr:DeleteRepository",
                "ecr:BatchDeleteImage",
                "ecr:SetRepositoryPolicy",
                "ecr:DeleteRepositoryPolicy",
                "ecr:GetAuthorizationToken",
                "ecr:BatchCheckLayerAvailability",
                "ecr:BatchGetImage"
            ]
        }
    ]
}
```

## Prepare instance

1. Clone the repository:
```shell
> mkdir datastore
> cd datastore
> git clone https://github.com/hcmc-project/rcdb_dashboard .
```
2. Install aws cli and docker-compose:
```shell
> pip3 install awscli docker-compose
```
3. Configure aws via cli. Set credentials of the ci/cd ecr user:
```shell
> aws configure
```
4. Install [docker](https://www.digitalocean.com/community/tutorials/how-to-install-docker-compose-on-ubuntu-18-04-ru).
5. Start db container:
```shell
> docker-compose -f docker-compose.yml -f docker-compose.awslogs.yml up -d db
```
6. Make `docker-compose` accessible from root user:
```shell
> sudo ln -sf /home/ubuntu/.local/bin/docker-compose /usr/bin/docker-compose
```

##  Prepare Github Actions
Set secrets:  
`AWS_DEFAULT_REGION` - aws region  
`AWS_ACCESS_KEY_ID` - aws credential with the policy to deploy to ECR  
`AWS_SECRET_ACCESS_KEY` - aws credential  
`DOCKER_REGISTRY` - url of the ECR private registry  
`SSH_USER` - ec2 instance user  
`SSH_HOST` - ec2 instance public ip    
`SSH_KEY` - ssh pem key    
`CREDENTIALSTORE_TOKEN` - token to 1p connect server  
`CREDENTIAL_STORE_ITEM_URL` - url to env document at 1p connect server, e.g. `http://<1p-connect-host:port>/v1/vaults/<vault-id>/items/<item-id>`  
`GH_TOKEN` - token of the ci user. to clone submodules  
Invoke the deployment pipeline on [the pipeline page](https://github.com/hcmc-project/rcdb_dashboard/actions/workflows/deploy.yml) by button `Run workflow`
