from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import DEFAULT_SOURCE, DevError, Environment, private_write, source_info
from .machine import Machine, scrub, show_report


def execute(argv, *, env=None, timeout=None):
    try:
        return subprocess.run(argv, env=env, timeout=timeout, check=False).returncode
    except FileNotFoundError:
        raise DevError(f'{argv[0]} is not installed. See devctl --usage for prerequisites.') from None


def compose(instance, *args, timeout=None):
    return execute(['docker', '--context', 'orbstack', 'compose', '--project-name', instance.project,
                    *[arg for path in instance.compose_files() for arg in ('--file', str(path))], *args], env=instance.process_env(), timeout=timeout)


def runtime_ready():
    if not shutil.which('orb'):
        raise DevError('OrbStack is missing. Install it and open the app once.')
    result = subprocess.run(['docker', '--context', 'orbstack', 'info', '--format', '{{.OSType}}'], capture_output=True, text=True)
    if result.returncode or result.stdout.strip() != 'linux':
        raise DevError("OrbStack's Docker engine is unavailable. Start OrbStack; other Docker contexts are not used.")


def provisioning_arguments(parser):
    parser.add_argument('--drop-in', type=Path, help='caller-supplied drop-in (required for SDK); existing workspace/state are retained')
    parser.add_argument('--manifest', type=Path, help='optional production provisioning manifest')
    parser.add_argument('--secrets-json', type=Path, help='optional private production secret bundle outside git')


def parser():
    p = argparse.ArgumentParser(description='Provision and test CRUX on isolated OrbStack Ubuntu.', epilog=(
        'Credentials: select the provider test key via direnv. Codex/SDK default to gpt-5.4-mini / low; Claude requires CRUX_MODEL. '
        'State is private under ~/.local/state/ciab-devenv/<name>. down stops the machine and containers.'))
    p.add_argument('--name', default='dev')
    p.add_argument('--usage', action='store_true')
    sub = p.add_subparsers(dest='command')
    s = sub.add_parser('plan', help='validate a Run with the selected source contracts; creates no environment')
    s.add_argument('--source', type=Path, required=True)
    s.add_argument('--spec', type=Path, required=True)
    for command in ('setup', 'bootstrap'):
        s = sub.add_parser(command, help='configure only' if command == 'setup' else 'configure, start services and provision Ubuntu')
        s.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
        s.add_argument('--scaffold', choices=('sdk', 'acp'), default='sdk')
        s.add_argument('--platform', choices=('openai-agents', 'codex', 'claude'))
        s.add_argument('--provider', choices=('direct', 'openrouter'), default='direct')
        s.add_argument('--port', type=int, default=23100)
        if command == 'bootstrap':
            provisioning_arguments(s)
    provisioning_arguments(sub.add_parser('provision', help='install/configure the selected source using production hooks'))
    s = sub.add_parser('select', help='select one source worktree; provision again before execution')
    s.add_argument('--source', type=Path, required=True)
    for command, description in (('up', 'start services and the existing Ubuntu machine; refresh service addresses'),
                                 ('status', 'show machine and service state'), ('doctor', 'check local service connectivity'),
                                 ('down', 'stop machine and containers, preserving data')):
        sub.add_parser(command, help=description)
    for command in ('run', 'check', 'probe'):
        s = sub.add_parser(command, help='run the selected scaffold with a wall time limit' if command == 'run' else 'execute the installed scaffold ' + command)
        s.add_argument('--timeout', type=int, default=900)
        if command == 'run':
            group = s.add_mutually_exclusive_group()
            group.add_argument('--prompt-file', type=Path, help='submit an ACP task from a text file')
            group.add_argument('--task-id', help='requeue and observe an existing ACP task')
    s = sub.add_parser('task', help='observe, reply to or cancel a local ACP task')
    s.add_argument('action', choices=('show', 'reply', 'cancel'))
    s.add_argument('task_id')
    s.add_argument('--message-file', type=Path)
    s = sub.add_parser('exec', help='execute a command as ubuntu using the provisioned scaffold environment')
    s.add_argument('--input', type=Path, help='copy a temporary directory read-only to /input')
    s.add_argument('--timeout', type=int, default=900)
    s.add_argument('argv', nargs=argparse.REMAINDER)
    for command in ('logs', 'restart'):
        s = sub.add_parser(command, help=f'{command} a service container')
        s.add_argument('service', nargs='?')
    s = sub.add_parser('fixture', help='inspect or steer local service fixtures')
    s.add_argument('action', choices=('show', 'reset', 'message', 'fail', 'recover'))
    s.add_argument('value', nargs='?', default='')
    s = sub.add_parser('report', help='read/export cached sanitized evidence, including while shut down')
    s.add_argument('run_id', nargs='?', default='latest')
    s.add_argument('--output', type=Path)
    s = sub.add_parser('reset', help='delete this instance machine, service volumes and private host state')
    s.add_argument('--confirm', required=True)
    s = sub.add_parser('machine', help='inspect the run machine or execute explicit root diagnostics')
    s.add_argument('action', choices=('status', 'exec'))
    s.add_argument('argv', nargs=argparse.REMAINDER)
    return p


def down(instance, machine):
    from devops.resources import lifecycle
    resources = lifecycle(instance, machine)
    if resources is not None:
        resources.check()
    try:
        machine.stop()
    finally:
        result = compose(instance, 'down')
    state = machine.state()
    if state and state['state'] == 'running':
        raise DevError('The machine is still running; inspect OrbStack before leaving this instance.')
    active = subprocess.check_output(['docker', '--context', 'orbstack', 'ps', '-q', '--filter',
                                      'label=com.docker.compose.project=' + instance.project], text=True).strip()
    if active:
        raise DevError('Instance containers are still running; inspect status.')
    return result


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    if args.usage or not args.command:
        p.print_help()
        if args.usage:
            for action in p._actions:
                if isinstance(action, argparse._SubParsersAction):
                    for command in action.choices.values():
                        print()
                        command.print_help()
        return 0
    operation_lock = None
    try:
        if args.command == 'plan':
            from devops.production import plan
            print(json.dumps(plan(args.source, args.spec), indent=2))
            return 0
        instance = Environment(args.name)
        if args.command not in ('status', 'logs', 'fixture', 'report', 'machine', 'task'):
            instance.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            operation_lock = os.fdopen(os.open(instance.root / 'operation.lock', os.O_CREAT | os.O_RDWR, 0o600), 'w')
            try:
                fcntl.flock(operation_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise DevError('Another environment command is running. Status, logs, reports and fixture controls remain available.') from None
        if args.command in ('setup', 'bootstrap'):
            if not 1024 <= args.port <= 65534:
                raise DevError('Choose a localhost port between 1024 and 65535.')
            instance.setup(args.source, args.port, args.scaffold, args.platform, args.provider)
            print(f'Configured {instance.name}: {instance.source}; private state: {instance.root}')
            if args.command == 'setup':
                return 0
        instance.source
        if args.command == 'report':
            return show_report(instance, args.run_id, args.output)
        machine = Machine(instance)
        if args.command == 'machine':
            if args.action == 'status':
                print(json.dumps(machine.state(), indent=2))
                return 0
            machine.require_running()
            command = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
            if not command:
                raise DevError('Provide a command after machine exec --')
            return machine.call(*command, check=False).returncode
        if args.command == 'down':
            return down(instance, machine)
        runtime_ready()
        if args.command in ('bootstrap', 'provision'):
            return machine.provision(args)
        if args.command == 'select':
            machine.require_idle()
            source = args.source.expanduser().resolve()
            instance.scaffold.validate_source(source)
            instance.data['source'] = str(source)
            private_write(instance.path, json.dumps(instance.data, indent=2) + '\n')
            machine.receipt.unlink(missing_ok=True)
            print('Source selected. Run provision --drop-in PATH to install it before testing.')
            return 0
        if args.command == 'up':
            machine.require_idle()
            if not (instance.root / 'certs/ca.crt').exists():
                raise DevError('This instance uses legacy TLS certificates. Reprovision before up.')
            if not machine.receipt.exists():
                raise DevError('Use bootstrap or provision --drop-in PATH to install the machine first.')
            from devops.resources import lifecycle
            resources = lifecycle(instance, machine)
            if resources is not None:
                resources.apply()
                result = 0
            else:
                result = compose(instance, 'up', '-d', '--wait', '--wait-timeout', '300')
            if not result:
                if resources is None:
                    machine.ensure()
                machine.network()
            return result
        if args.command == 'status':
            print(json.dumps({'instance': instance.name, 'source': source_info(instance.source),
                              'machine': machine.state(), 'provisioned': machine.receipt.exists(), 'scaffold': instance.scaffold.name,
                              'platform': instance.scaffold.platform,
                              'agentrq': f'https://localhost:{instance.data["port"] + 1}' if instance.scaffold.name == 'acp' else None,
                              'langfuse': f'http://localhost:{instance.data["port"]}', 'private_state': str(instance.root)}, indent=2))
            return compose(instance, 'ps')
        if args.command in ('logs', 'restart'):
            command = [args.command, *(['--tail', '100'] if args.command == 'logs' else [])]
            if args.service:
                command.append(args.service)
            if args.command == 'logs':
                result = subprocess.run(['docker', '--context', 'orbstack', 'compose', '--project-name', instance.project,
                                         *[arg for path in instance.compose_files() for arg in ('--file', str(path))], *command], env=instance.process_env(),
                                        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                print(scrub(result.stdout, instance.process_env()))
                return result.returncode
            return compose(instance, *command)
        if args.command == 'task':
            from .acp import task_control
            return task_control(machine, args)
        if args.command in ('run', 'check', 'probe', 'exec'):
            if args.timeout < 1:
                raise DevError('--timeout must be positive.')
            if instance.scaffold.name == 'acp' and args.command in ('run', 'probe'):
                from .acp import run_task
                return run_task(machine, args)
            if getattr(args, 'prompt_file', None) or getattr(args, 'task_id', None):
                raise DevError('Task inputs require --scaffold acp.')
            command = getattr(args, 'argv', [])
            if command[:1] == ['--']:
                command = command[1:]
            if args.command == 'exec' and not command:
                raise DevError('Provide a command after exec.')
            return machine.job(args.command, command, args.timeout, getattr(args, 'input', None))
        if args.command == 'doctor':
            if instance.scaffold.name == 'acp':
                from .agentrq import Client
                workspace = Client(instance).workspace()
                print('PASS AgentRQ authentication and workspace; agent connected: ' + str(workspace.get('agentConnected', False)))
            return machine.job('services')
        if args.command == 'fixture':
            return machine.job('fixture', [args.action, args.value])
        if args.command == 'reset':
            if args.confirm != instance.name:
                raise DevError('--confirm must match the instance name. Reset deletes its machine, runs and service data.')
            machine.require_idle()
            from devops.resources import lifecycle
            resources = lifecycle(instance, machine)
            if resources is not None and resources.path.exists():
                resources.destroy()
                result = 0
            elif resources is not None:
                resources.check()
                if machine.state():
                    raise DevError('Machine exists without a resource receipt; inspect ownership before deletion.')
                result = compose(instance, 'down', '--volumes', '--remove-orphans')
            else:
                machine.delete()
                result = compose(instance, 'down', '--volumes', '--remove-orphans')
            if not result:
                shutil.rmtree(instance.root)
            return result
        raise DevError('Unsupported command')
    except (DevError, ValueError, TypeError, OSError, subprocess.CalledProcessError) as exc:
        print(f'devctl: {exc}', file=sys.stderr)
        return 2
    finally:
        if operation_lock is not None:
            operation_lock.close()
