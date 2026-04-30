#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib/core';
import { AwsStack } from '../lib/aws-stack';

const app = new cdk.App();
new AwsStack(app, 'alphastell', {
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: 'ap-northeast-1' },
});
