#!/usr/bin/env bash
source .env
aws ecr get-login-password --region $AWS_DEFAULT_REGION | docker login --username AWS --password-stdin $DOCKER_REGISTRY && echo 'Successful login to ECR'

docker-compose pull web nginx && echo "Successful pulled images"
docker-compose down

while test $# -gt 0; do
  case "$1" in
    -m|--migrate)
      echo "Starting migration"
      docker-compose run web bash -c "./manage.py migrate"
      docker-compose down
      break
      ;;
    esac
done

docker rmi $(docker images --filter "dangling=true" -q --no-trunc) && echo "Successful removed old images"
docker-compose -f docker-compose.yml -f docker-compose.awslogs.yml up -d
docker-compose ps
echo 'Deploy ended'
