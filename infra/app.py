#!/usr/bin/env python3
import aws_cdk as cdk

from lib.revolver_auth_stack import ReVolverAuthStack

app = cdk.App()

# Stage selection: `cdk deploy` → prod (default), `cdk deploy -c stage=dev` → dev.
stage = app.node.try_get_context("stage") or "prod"
if stage not in ("prod", "dev"):
    raise ValueError(f"Unknown stage '{stage}', expected 'prod' or 'dev'")

# Prod keeps the original stack name so its resources and Function URL are unchanged.
stack_id = "ReVolverAuthStack" if stage == "prod" else f"ReVolverAuthStack-{stage}"
ReVolverAuthStack(app, stack_id, stage=stage)
app.synth()
