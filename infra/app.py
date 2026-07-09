#!/usr/bin/env python3
import aws_cdk as cdk

from lib.revolver_auth_stack import ReVolverAuthStack

app = cdk.App()
ReVolverAuthStack(app, "ReVolverAuthStack")
app.synth()
