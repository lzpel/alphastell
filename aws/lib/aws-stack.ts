import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';

export class AwsStack extends cdk.Stack {
	constructor(scope: Construct, id: string, props?: cdk.StackProps) {
		super(scope, id, props);

		// Lambda関数 (../ ディレクトリの Dockerfile を image asset としてビルド)
		// frontend-embed feature ON でビルドされ、frontend/out/ をバイナリに焼き込み済み。
		const { lambda: apiFunction, lambda_url: functionUrl } = docker_image_function(
			this,
			"ApiFunction",
			path.join(__dirname, "..", ".."),
			{
				timeout: cdk.Duration.minutes(15),
				memorySize: 2048,
				environment: {
					AWS_LWA_INVOKE_MODE: "response_stream",
				},
			},
			{
				invokeMode: lambda.InvokeMode.RESPONSE_STREAM,
				cors: {
					allowedMethods: [lambda.HttpMethod.ALL],
					allowedOrigins: ["*"],
					allowedHeaders: ["*"],
				},
			}
		);
		// CloudFront: 単一 origin = Lambda Function URL
		const distribution = new cloudfront.Distribution(this, 'ApiDistribution', {
			defaultBehavior: {
				origin: new origins.FunctionUrlOrigin(functionUrl, {
					readTimeout: cdk.Duration.seconds(60),
				}),
				viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
				allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
				cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED, // 動的 API なのでキャッシュ無効
				originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
			},
		});

		new cdk.CfnOutput(this, 'FunctionUrl', { value: functionUrl.url });
		new cdk.CfnOutput(this, 'DistributionDomainName', { value: distribution.domainName });
	}
}

const docker_image_function = (
	construct: Construct,
	id: string,
	directory: string,
	props_lambda?: Omit<cdk.aws_lambda.DockerImageFunctionProps, "code">,
	props_url?: Omit<cdk.aws_lambda.FunctionUrlOptions, "authType">
) => {
	const lambda = new cdk.aws_lambda.DockerImageFunction(construct, id, {
		code: cdk.aws_lambda.DockerImageCode.fromImageAsset(directory),
		...props_lambda
	});
	const lambda_url = lambda.addFunctionUrl({
		authType: cdk.aws_lambda.FunctionUrlAuthType.NONE,
		...props_url
	})
	return { lambda, lambda_url }
}
