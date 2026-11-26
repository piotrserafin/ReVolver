from aws_cdk import (
    Stack,
    Duration,
    CfnOutput,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_iam as iam,
    aws_ssm as ssm,
    aws_sns as sns,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_logs as logs,
)
from constructs import Construct


# The Function URL is public (it ships in every .pbw). No reserved concurrency:
# the account's whole Lambda limit is 10 (checked 2026-11-26) and AWS keeps 10
# unreserved, so reserving any fails the deploy. That limit is the cap for now:
# above 10 concurrent requests (prod + dev together) callers get 429. If the
# quota is ever raised, reserve ~10 for prod here.
# Alarm when an hour has more requests than real users ever make.
INVOCATIONS_PER_HOUR_ALARM = {"prod": 1000, "dev": 200}


class ReVolverAuthStack(Stack):

    def __init__(
        self, scope: Construct, id: str, *, stage: str = "prod", **kwargs
    ) -> None:
        super().__init__(scope, id, **kwargs)

        stack = Stack.of(self)

        # ─── SSM Parameters (created manually once, read at runtime) ───
        # Store secrets with (prefix /revolver for prod, /revolver-dev for dev):
        #   aws ssm put-parameter --name /revolver/client-id --value "xxx" --type SecureString
        #   aws ssm put-parameter --name /revolver/client-secret --value "xxx" --type SecureString
        #   aws ssm put-parameter --name /revolver/redirect-uri --value "https://..." --type String
        #   aws ssm put-parameter --name /revolver/allowed-origins --value "https://piotrserafin.github.io,https://piotrserafin.dev" --type String
        #
        # Dev uses a separate prefix, not /revolver/dev: the prod policy grants
        # parameter/revolver/*, which would let prod read dev secrets.

        ssm_prefix = "/revolver" if stage == "prod" else f"/revolver-{stage}"
        description_suffix = "" if stage == "prod" else f" ({stage})"

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

        # Browser-login pairing. Items live 10 min; nothing
        # worth keeping, so the table goes with the stack.
        pairing_table = dynamodb.Table(
            self,
            "PairingTable",
            table_name=f"{stack.stack_name}-pairing",
            partition_key=dynamodb.Attribute(
                name="code", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Own log group so the stack sets retention. The handler logs one JSON
        # line per event, never bodies or tokens.
        log_group = logs.LogGroup(
            self,
            "TokenExchangeLogs",
            log_group_name=f"/revolver/{stack.stack_name}/token-exchange",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # Token exchange Lambda
        token_function = lambda_.Function(
            self,
            "TokenExchangeFunction",
            description="ReVolver OAuth2 token exchange proxy for Volvo ID"
            + description_suffix,
            code=lambda_.Code.from_asset(
                "lambda",  # infra/lambda/
                exclude=["test_*.py", "__pycache__", "README.md"],
            ),
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="token_exchange.lambda_handler",
            # CPU scales with memory. At 128 MB the cold start (boto3 import,
            # clients, SSM) took ~6 s, on almost every app launch.
            memory_size=1024,
            # VOLVO_TIMEOUT_SECONDS (8) fits inside, so a slow Volvo gets a 504.
            timeout=Duration.seconds(10),
            role=lambda_role,
            log_group=log_group,
            function_name=f"{stack.stack_name}-token-exchange",
            environment={
                # Only the SSM prefix — no secrets in env vars or CloudFormation
                "SSM_PREFIX": ssm_prefix,
                "PAIRING_TABLE": pairing_table.table_name,
            },
        )

        pairing_table.grant(
            lambda_role,
            "dynamodb:PutItem",
            "dynamodb:GetItem",
            "dynamodb:UpdateItem",
            "dynamodb:DeleteItem",
        )

        # Function URL (CORS handled by Lambda for dynamic origin matching)
        function_url = token_function.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
        )

        # ─── Alarms ───
        # Email subscription is added by hand (infra/lambda/README.md, "Alarms"),
        # so no address ends up in the repo or the template.
        alarm_topic = sns.Topic(
            self,
            "AlarmTopic",
            topic_name=f"{stack.stack_name}-alarms",
            display_name="ReVolver alarms" + description_suffix,
        )
        notify = cw_actions.SnsAction(alarm_topic)

        throttles = cloudwatch.Alarm(
            self,
            "ThrottlesAlarm",
            alarm_name=f"{stack.stack_name}-throttles",
            alarm_description="Token Lambda hit its concurrency cap: flood, or users getting 429s",
            metric=token_function.metric_throttles(
                period=Duration.minutes(5), statistic="Sum"
            ),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        invocations = cloudwatch.Alarm(
            self,
            "InvocationsAlarm",
            alarm_name=f"{stack.stack_name}-invocations",
            alarm_description="Token Lambda traffic far above normal use",
            metric=token_function.metric_invocations(
                period=Duration.hours(1), statistic="Sum"
            ),
            threshold=INVOCATIONS_PER_HOUR_ALARM[stage],
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        # The handler catches every exception (so Lambda's Errors metric stays 0)
        # and logs {"level": "error", ...} instead: unhandled bugs, missing config.
        handler_errors = logs.MetricFilter(
            self,
            "HandlerErrorsFilter",
            log_group=log_group,
            filter_pattern=logs.FilterPattern.string_value("$.level", "=", "error"),
            metric_namespace="ReVolver",
            metric_name=f"{stack.stack_name}-handler-errors",
            metric_value="1",
        )
        errors = cloudwatch.Alarm(
            self,
            "HandlerErrorsAlarm",
            alarm_name=f"{stack.stack_name}-handler-errors",
            alarm_description="Token Lambda logged an error: unhandled exception or missing SSM config",
            metric=handler_errors.metric(period=Duration.minutes(5), statistic="Sum"),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        )
        for alarm in (throttles, invocations, errors):
            alarm.add_alarm_action(notify)

        CfnOutput(
            self,
            "AlarmTopicArn",
            value=alarm_topic.topic_arn,
            description="Subscribe an email to get alarms (see infra/lambda/README.md)",
        )

        CfnOutput(
            self,
            "TokenExchangeUrl",
            value=function_url.url,
            description="ReVolver token exchange endpoint — set this in index.html",
        )
