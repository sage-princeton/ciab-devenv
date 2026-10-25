"""Bounded AgentRQ tasks; controller administrator credentials remain on the host."""
from datetime import datetime, timezone
from pathlib import Path
import json
import hashlib
import time

from .agentrq import Client
from .config import DevError, ROOT, private_write, source_info
from .machine import new_id, scrub


def task_control(machine, args):
    if machine.instance.scaffold.name != 'acp':
        raise DevError('Task controls require an ACP instance.')
    receipt = machine.require_provisioned()
    directory = machine.instance.root / 'reports' / new_id()
    data = dict(receipt, suite='task-' + args.action, task_id=args.task_id,
                run_id=directory.name, devenv=source_info(ROOT), command=['devctl', 'task', args.action, args.task_id])
    started = time.monotonic()
    code = 2
    log = []
    try:
        client = Client(machine.instance)
        task = client.task(args.task_id)['task']
        if args.action == 'reply':
            if not args.message_file:
                raise DevError('Reply requires --message-file PATH.')
            message = args.message_file.read_text()
            data['message_sha256'] = hashlib.sha256(message.encode()).hexdigest()
            client.task(args.task_id, '/reply', {'reply': {'text': message}})
        elif args.action == 'cancel' and task['status'] not in ('completed', 'rejected'):
            if any(t['id'] != args.task_id for t in client.tasks('ongoing')):
                raise DevError('Another task is running; refusing to stop its gateway.')
            try:
                client.task(args.task_id, '/stop', {})
            except (DevError, OSError) as error:
                log.append(f'Stop notification unavailable; stopping the local service: {error}')
            try:
                client.task(args.task_id, '/status', {'status': {'value': 'rejected'}}, 'PATCH')
            finally:
                machine.stop_run()
        data['task'] = client.task(args.task_id)['task']
        code = 0
    except Exception as error:
        log.append(f'{type(error).__name__}: {error}')
    data.update(exit_code=code, status='succeeded' if code == 0 else 'failed',
                elapsed_seconds=round(time.monotonic() - started, 2))
    values = machine.instance.redactions()
    private_write(directory / 'report.json', scrub(json.dumps(data, indent=2), values) + '\n')
    private_write(directory / 'output.log', scrub('\n'.join(log), values))
    print(scrub(json.dumps(data.get('task', {}), indent=2), values))
    if log:
        print(scrub('\n'.join(log), values))
    print(f'Evidence: {directory}/report.json; status={data["status"]}')
    return code


def run_task(machine, args):
    receipt = machine.require_provisioned()
    machine.require_idle()
    client = Client(machine.instance)
    task_id = getattr(args, 'task_id', None)
    active = client.tasks()
    if any(t['id'] != task_id for t in active):
        raise DevError('Workspace has unfinished tasks. Resume with --task-id or cancel them first.')
    if args.command == 'probe':
        prompt = 'Reply exactly ACP-PROBE and mark this task completed. Do not change files.'
    elif getattr(args, 'prompt_file', None):
        prompt = args.prompt_file.read_text()
    elif not task_id:
        raise DevError('ACP run requires --prompt-file PATH or --task-id ID.')
    if task_id:
        client.task(task_id)
        client.task(task_id, '/status', {'status': {'value': 'notstarted'}}, 'PATCH')
    run_id = new_id()
    directory = machine.instance.root / 'reports' / run_id
    started = time.monotonic()
    data = dict(receipt, run_id=run_id, suite=args.command, timeout=args.timeout,
                started_at=datetime.now(timezone.utc).isoformat(), devenv=source_info(ROOT),
                machine=machine.name, events=[], status='running',
                command=['devctl', args.command],
                input={'task_id': task_id} if task_id else {'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest()})
    directory.mkdir(parents=True, mode=0o700)
    log = []
    code = 2
    service = machine.instance.scaffold.service
    try:
        machine.call('systemctl', 'start', *machine.run_units())
        while not client.workspace().get('agentConnected'):
            if time.monotonic() - started >= min(args.timeout, 60):
                raise TimeoutError('ACP gateway did not connect to its workspace.')
            time.sleep(1)
        if not task_id:
            task_id = client.create(prompt, 'Local run ' + run_id)['id']
        data['task_id'] = task_id
        private_write(directory / 'report.json', json.dumps(data, indent=2))
        print(f'AgentRQ task {task_id}; evidence: {directory}/report.json', flush=True)
        previous = None
        while True:
            task = client.task(task_id)['task']
            state = task['status']
            if state != previous:
                data['events'].append({'status': state, 'elapsed_seconds': round(time.monotonic() - started, 2)})
                print('Task status: ' + state, flush=True)
                previous = state
            if state in ('completed', 'rejected', 'blocked'):
                code = 0 if state == 'completed' else 3
                data['task'] = task
                break
            if time.monotonic() - started >= args.timeout:
                raise TimeoutError('Task exceeded the wall time limit.')
            state_result = machine.call('systemctl', 'is-active', service, capture=True, check=False)
            if state_result.stdout.strip() != 'active':
                if client.task(task_id)['task']['status'] in ('completed', 'rejected', 'blocked'):
                    continue
                raise DevError('ACP gateway exited before task completion.')
            time.sleep(1)
    except KeyboardInterrupt:
        code = 130
        log.append('Interrupted by operator.')
    except TimeoutError as error:
        code = 124
        log.append(str(error))
    except Exception as error:
        log.append(f'{type(error).__name__}: {error}')
    finally:
        if code and task_id:
            try:
                client.task(task_id, '/stop', {})
            except Exception as error:
                log.append(f'Stop notification unavailable: {error}')
        try:
            machine.stop_run()
        except Exception as error:
            log.append(f'Service cleanup failed: {error}')
            code = code or 2
        if code in (124, 130) and task_id:
            try:
                client.task(task_id, '/status', {'status': {'value': 'rejected'}}, 'PATCH')
            except Exception as error:
                log.append(f'Task cancellation state unavailable: {error}')
        try:
            snapshot_code = machine.job('snapshot', [data['started_at']], timeout=30)
            if isinstance(machine.last_report, Path):
                data['snapshot_report'] = str(machine.last_report / 'report.json')
                private_write(directory / 'machine.json', (machine.last_report / 'report.json').read_text())
                log.append((machine.last_report / 'output.log').read_text())
            code = code or snapshot_code
        except Exception as error:
            log.append(f'Evidence snapshot failed: {error}')
            code = code or 2
        if task_id:
            try:
                data['task'] = client.task(task_id)['task']
            except Exception as error:
                log.append(f'Final task state unavailable: {error}')
        data.update(status='succeeded' if code == 0 else 'failed', exit_code=code,
                    elapsed_seconds=round(time.monotonic() - started, 2))
        private_write(directory / 'report.json', scrub(json.dumps(data, indent=2), machine.instance.redactions()) + '\n')
        private_write(directory / 'output.log', scrub('\n'.join(log), machine.instance.redactions()))
        print(scrub('\n'.join(log), machine.instance.redactions()))
        print(f'Evidence: {directory}/report.json; status={data["status"]}')
    return code
