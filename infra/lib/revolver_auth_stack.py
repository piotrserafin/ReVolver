from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_ssm as ssm,
)
from constructs import Construct


class ReVolverAuthStack(Stack):

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        stack = Stack.of(self)

        # ─── SSM Parameters (created manually once, read at runtime) ───
        # Store secrets with:
        #   aws ssm put-parameter --name /revolver/client-id --value "xxx" --type SecureString
        #   aws ssm put-parameter --name /revolver/client-secret --value "xxx" --type SecureString
        #   aws ssm put-parameter --name /revolver/redirect-uri --value "https://..." --type String
        #   aws ssm put-parameter --name /revolver/allowed-origins --value "https://piotrserafin.github.io,https://piotrserafin.dev" --type String

        ssm_prefix = "/revolver"

        # Execution role with SSM read access
        lambda_role = iam.Role(
            self,
            "LambdaExecutionRole",
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            role_name=f"{stack.stack_name}-lambda-role",
            managed_policies=[
                iam.ManagedPolicy.from_aws_managed_policy_name(
                    "service-role/AWSLambdaBasicExecutionRole"
                ),
            ],
            inline_policies={
                "ssm-read": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=[
                                "ssm:GetParameter",
                                "ssm:GetParameters",
                            ],
                            resources=[
                                f"arn:aws:ssm:{stack.region}:{stack.account}:parameter{ssm_prefix}/*"
                            ],
                        ),
                        # Allow decryption of SecureString parameters via SSM only
                        iam.PolicyStatement(
                            actions=["kms:Decrypt"],
                            resources=["*"],
                            conditions={
                                "StringEquals": {
                                    "kms:ViaService": f"ssm.{stack.region}.amazonaws.com"
                                },
                                "ArnLike": {
                                    "kms:EncryptionContext:PARAMETER_ARN":
                                        f"arn:aws:ssm:{stack.region}:{stack.account}:parameter{ssm_prefix}/*"
                                },
                            },
                        ),
                    ]
                )
            },
        )

        # Token exchange Lambda
        token_function = lambda_.Function(
            self,
            "TokenExchangeFunction",
            description="ReVolver OAuth2 token exchange proxy for Volvo ID",
            code=lambda_.Code.from_asset("lambda"),  # infra/lambda/
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="token_exchange.lambda_handler",
            memory_size=128,
            timeout=Duration.seconds(10),
            role=lambda_role,
            function_name=f"{stack.stack_name}-token-exchange",
            environment={
                # Only the SSM prefix — no secrets in env vars or CloudFormation
                "SSM_PREFIX": ssm_prefix,
            },
        )

        # Function URL (CORS handled by Lambda for dynamic origin matching)
        function_url = token_function.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )

        CfnOutput(
            self,
            "TokenExchangeUrl",
            value=function_url.url,
            description="ReVolver token exchange endpoint — set this in index.html",
        )
