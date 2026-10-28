"""
Retry rules of every state machine in this component, and the Lambdas they invoke.

Lambdas do not retry; the state machines do, and they retry only errors they can name:
- every Lambda a state machine invokes decorates its handler with transient_aws_errors (aws_errors.py,
  distributed by Installer/refresh and packaged as this component's AwsErrorsLayer), so throttling,
  AWS-side failures and connection problems leave it as AWSTransientError;
- every Lambda state retries AWSTransientError and the Lambda service errors with one rule: 5 s, doubling,
  at most 300 s apart, full jitter, 20 attempts; other rules may retry other named errors only, except that
  a rule of its own may give Lambda concurrency throttling (Lambda.TooManyRequestsException) more time;
- nothing is retried on a wildcard (States.ALL, States.TaskFailed);
- every retrier has full jitter and waits at most 300 s, so concurrent executions do not retry in lockstep
  and backoff does not grow without bound.
"""

import ast
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent.parent
DEFINITIONS = sorted(p for pattern in ('statemachine*/**/*.asl.yaml', 'statemachine*/**/*.asl.yml',
                                       'statemachine*/**/*.asl.json') for p in ROOT.glob(pattern))
LAMBDA_SERVICE_ERRORS = {'Lambda.ServiceException', 'Lambda.AWSLambdaException', 'Lambda.SdkClientException',
                         'Lambda.TooManyRequestsException'}
TRANSIENT_RULE = {'IntervalSeconds': 5, 'MaxAttempts': 20, 'BackoffRate': 2, 'MaxDelaySeconds': 300,
                  'JitterStrategy': 'FULL'}
WILDCARDS = {'States.ALL', 'States.TaskFailed'}


class CfnLoader(yaml.SafeLoader):
    pass


CfnLoader.add_multi_constructor(
    '!', lambda loader, suffix, node: {f'!{suffix}': loader.construct_scalar(node)
                                      if isinstance(node, yaml.ScalarNode) else loader.construct_sequence(node)
                                      if isinstance(node, yaml.SequenceNode) else loader.construct_mapping(node)})

TEMPLATE = yaml.load((ROOT / 'template.yaml').read_text(), Loader=CfnLoader)
RESOURCES = TEMPLATE['Resources']


def functions_by_substitution():
    """'${XFunctionArn}' -> logical function name, from every state machine's DefinitionSubstitutions."""
    found = {}
    for resource in RESOURCES.values():
        if resource.get('Type') not in ('AWS::Serverless::StateMachine', 'AWS::StepFunctions::StateMachine'):
            continue
        for key, value in (resource['Properties'].get('DefinitionSubstitutions') or {}).items():
            if isinstance(value, dict) and '!GetAtt' in value:
                target = value['!GetAtt']
                name = target.split('.')[0] if isinstance(target, str) else target[0]
                if RESOURCES.get(name, {}).get('Type') == 'AWS::Serverless::Function':
                    found['${' + key + '}'] = name
    return found


FUNCTIONS = functions_by_substitution()


def load(path):
    text = path.read_text()
    return json.loads(text) if path.suffix == '.json' else yaml.safe_load(text)


def all_states(states, prefix=''):
    for name, state in states.items():
        yield prefix + name, state
        for key in ('Iterator', 'ItemProcessor'):
            if key in state:
                yield from all_states(state[key]['States'], f'{prefix}{name} > ')
        for branch in state.get('Branches', []):
            yield from all_states(branch['States'], f'{prefix}{name} > ')


STATES = [(path.name, name, state) for path in DEFINITIONS for name, state in all_states(load(path)['States'])]
RETRYING = [s for s in STATES if s[2].get('Retry')]
LAMBDA_STATES = [(sm, name, state, FUNCTIONS[state['Resource']]) for sm, name, state in STATES
                 if state.get('Type') == 'Task' and state.get('Resource') in FUNCTIONS]


def ids(cases):
    return [f'{case[0]}:{case[1]}' for case in cases]


def matches(error_equals, error):
    if 'States.ALL' in error_equals:
        return True
    if 'States.TaskFailed' in error_equals and error != 'States.Timeout':
        return True
    return error in error_equals


def retried(state, error, attempt):
    """Whether Step Functions retries `error` on the given attempt (0 = first failure)."""
    for retrier in state.get('Retry', []):
        if matches(retrier['ErrorEquals'], error):
            return attempt < retrier.get('MaxAttempts', 3)
    return False


def transient_rules(state):
    return [r for r in state.get('Retry', []) if 'AWSTransientError' in r['ErrorEquals']]


def test_the_scan_finds_the_states():
    """Guard against the tests silently matching nothing."""
    assert DEFINITIONS
    assert LAMBDA_STATES


@pytest.mark.parametrize('sm, name, state', RETRYING, ids=ids(RETRYING))
def test_every_retrier_has_full_jitter_and_waits_at_most_300_seconds(sm, name, state):
    for retrier in state['Retry']:
        assert retrier.get('JitterStrategy') == 'FULL', retrier
        assert retrier.get('MaxDelaySeconds') == 300, retrier


@pytest.mark.parametrize('sm, name, state', RETRYING, ids=ids(RETRYING))
def test_nothing_is_retried_on_a_wildcard(sm, name, state):
    for retrier in state['Retry']:
        assert not WILDCARDS & set(retrier['ErrorEquals']), retrier


@pytest.mark.parametrize('sm, name, state, function', LAMBDA_STATES, ids=ids(LAMBDA_STATES))
class TestLambdaState:

    def test_has_one_transient_rule(self, sm, name, state, function):
        assert len(transient_rules(state)) == 1

    def test_the_transient_rule_retries_aws_and_lambda_service_errors_only(self, sm, name, state, function):
        errors = set(transient_rules(state)[0]['ErrorEquals'])
        assert {'AWSTransientError', *LAMBDA_SERVICE_ERRORS} <= errors <= \
            {'AWSTransientError', 'States.Timeout', *LAMBDA_SERVICE_ERRORS}

    def test_the_transient_rule_backs_off_from_5_to_at_most_300_seconds_20_times(self, sm, name, state, function):
        rule = {k: v for k, v in transient_rules(state)[0].items() if k != 'ErrorEquals'}
        assert rule == TRANSIENT_RULE

    def test_other_rules_retry_other_named_errors_only(self, sm, name, state, function):
        for retrier in state['Retry']:
            if retrier in transient_rules(state) or retrier['ErrorEquals'] == ['Lambda.TooManyRequestsException']:
                continue
            assert not {'AWSTransientError', *LAMBDA_SERVICE_ERRORS, *WILDCARDS} & set(retrier['ErrorEquals'])

    def test_a_concurrency_rule_of_its_own_comes_first_and_waits_at_least_as_long(self, sm, name, state, function):
        own = [r for r in state['Retry'] if r['ErrorEquals'] == ['Lambda.TooManyRequestsException']]
        if own:
            assert state['Retry'].index(own[0]) < state['Retry'].index(transient_rules(state)[0])
            assert own[0]['MaxAttempts'] >= TRANSIENT_RULE['MaxAttempts']

    @pytest.mark.parametrize('attempt', [0, 19])
    def test_a_throttled_aws_call_is_retried(self, sm, name, state, function, attempt):
        assert retried(state, 'AWSTransientError', attempt)

    def test_and_given_up_after_20_attempts(self, sm, name, state, function):
        assert not retried(state, 'AWSTransientError', 20)

    @pytest.mark.parametrize('error', ['KeyError', 'ClientError', 'Sandbox.Timedout', 'States.TaskFailed'])
    def test_other_errors_are_not_retried(self, sm, name, state, function, error):
        assert not retried(state, error, 0)


# ---------------------------------------------------------------------------
# The Lambdas and the layer
# ---------------------------------------------------------------------------

INVOKED = sorted({function for *_, function in LAMBDA_STATES})


def handler_source(function):
    """The handler's source file, from CodeUri and Handler (each possibly set in Globals)."""
    properties, globals_ = RESOURCES[function]['Properties'], TEMPLATE.get('Globals', {}).get('Function', {})
    code_uri = properties.get('CodeUri', globals_.get('CodeUri'))
    handler = properties.get('Handler', globals_.get('Handler'))
    return ROOT / code_uri / f"{handler.rsplit('.', 1)[0]}.py"


@pytest.mark.parametrize('function', INVOKED)
def test_every_invoked_lambda_names_its_transient_aws_errors(function):
    tree = ast.parse(handler_source(function).read_text())
    handler = next(node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == 'lambda_handler')
    assert 'transient_aws_errors' in [d.id for d in handler.decorator_list if isinstance(d, ast.Name)]


def test_the_layer_packages_aws_errors():
    layer = RESOURCES['AwsErrorsLayer']
    assert layer['Type'] == 'AWS::Serverless::LayerVersion'
    assert layer['Properties']['ContentUri'] == 'functions/layers/aws_errors/'
    assert (ROOT / 'functions' / 'layers' / 'aws_errors' / 'python' / 'aws_errors.py').is_file()


def test_every_function_has_the_layer():
    assert {'!Ref': 'AwsErrorsLayer'} in TEMPLATE['Globals']['Function']['Layers']
