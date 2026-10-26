"""Local AgentRQ provisioning and its authenticated, workspace-scoped API."""
from __future__ import annotations

import hashlib
import http.cookiejar
import json
import re
import shlex
import ssl
import subprocess
import urllib.error
import urllib.request

from .config import DevError, private_write
from devops.source import source_path

PIN_KEYS = ('ACP_GATEWAY_VERSION', 'ACP_GATEWAY_TARBALL_URL', 'ACP_GATEWAY_SHA256',
            'CODEX_VERSION', 'CODEX_ACP_VERSION', 'TRACING_PLUGIN_VERSION', 'TRACING_HOOK_TRUSTED_HASH',
            'CLAUDE_VERSION', 'CLAUDE_ACP_VERSION', 'CODEX_TRACE_MODE')


def assignments(path, keys):
    text = path.read_text()
    result = {}
    for key in keys:
        match = re.search(r'^' + re.escape(key) + r'=([^\s#]+)\s*$', text, re.MULTILINE)
        if match:
            result[key] = shlex.split(match[1])[0]
    return result


def pins(source):
    result = assignments(source_path(source, 'workspace', 'placeholders-base.txt.example'), PIN_KEYS)
    result.update(assignments(source_path(source, 'controller', 'configure-control.sh'),
                              ('AGENTRQ_IMAGE', 'AGENTRQ_IMAGE_URL', 'AGENTRQ_IMAGE_SHA256', 'AGENTRQ_SQLITE_DSN')))
    required = ('AGENTRQ_IMAGE',)
    if '@sha256:' not in result.get('AGENTRQ_IMAGE', ''):
        required += ('AGENTRQ_IMAGE_URL', 'AGENTRQ_IMAGE_SHA256')
    for key in required:
        if key not in result:
            raise DevError('Selected source does not declare ' + key)
    return result


def prepare_image(instance, settings):
    image = settings['AGENTRQ_IMAGE']
    if '@sha256:' in image:
        if not re.fullmatch(r'[^\s@]+@sha256:[a-f0-9]{64}', image):
            raise DevError('AgentRQ registry image needs a sha256 digest pin.')
        subprocess.run(['docker', '--context', 'orbstack', 'pull', image], check=True, capture_output=True)
    else:
        load_archive(instance, settings)
    info = json.loads(subprocess.check_output(['docker', '--context', 'orbstack', 'image', 'inspect',
                                               image], text=True))[0]
    instance.data['agentrq_image'] = info['Id']
    instance.data['agentrq_architecture'] = info['Architecture']
    instance.data['agentrq_sqlite_dsn'] = settings.get('AGENTRQ_SQLITE_DSN', '/_storage/agentrq.db')
    private_write(instance.path, json.dumps(instance.data, indent=2) + '\n')


def load_archive(instance, settings):
    archive = instance.root / 'agentrq-image.tar.gz'
    expected = settings['AGENTRQ_IMAGE_SHA256']
    if not re.fullmatch('[a-f0-9]{64}', expected):
        raise DevError('AgentRQ image needs a sha256 pin.')
    def digest():
        with archive.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    if not archive.exists() or digest() != expected:
        subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', '--max-time', '300',
                        settings['AGENTRQ_IMAGE_URL'], '--output', str(archive)], check=True)
        if digest() != expected:
            archive.unlink()
            raise DevError('AgentRQ image archive does not match the selected source hash.')
    subprocess.run(['docker', '--context', 'orbstack', 'load', '-i', str(archive)], check=True, capture_output=True)


class Client:
    def __init__(self, instance):
        self.instance = instance
        self.base = f'https://localhost:{instance.data["port"] + 1}/api/v1'
        context = ssl.create_default_context(cafile=str(instance.root / 'certs/ca.crt'))
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
            urllib.request.HTTPSHandler(context=context), urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.request('/auth/root/login', {'rootToken': instance.data['agentrq_root_token']})
        self.request('/auth/user')

    def request(self, path, body=None, method=None):
        request = urllib.request.Request(self.base + path, method=method,
            data=None if body is None else json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=15) as response:
                data = response.read()
                return json.loads(data) if data and response.headers.get_content_type() == 'application/json' else {}
        except urllib.error.HTTPError as error:
            raise DevError(f'Local AgentRQ {method or ("POST" if body is not None else "GET")} {path}: HTTP {error.code}') from None

    @property
    def workspace_path(self):
        return '/workspaces/' + self.instance.data['agentrq_workspace_id']

    def workspace(self):
        return self.request(self.workspace_path)['workspace']

    def tasks(self, status='notstarted,ongoing,blocked'):
        result = []
        while True:
            page = self.request(self.workspace_path + f'/tasks?status={status}&limit=50&offset={len(result)}')['tasks']
            result.extend(page)
            if len(page) < 50:
                return result

    def task(self, task_id, suffix='', body=None, method=None):
        if not re.fullmatch('[A-Za-z0-9]+', task_id):
            raise DevError('Invalid AgentRQ task ID.')
        return self.request(self.workspace_path + '/tasks/' + task_id + suffix, body, method)

    def create(self, prompt, title):
        return self.request(self.workspace_path + '/tasks', {'task': {
            'title': title, 'body': prompt, 'createdBy': 'human', 'assignee': 'agent',
            'status': 'notstarted', 'allowAllCommands': True}})['task']

    def bootstrap(self):
        if self.instance.data.get('agentrq_workspace_id'):
            self.workspace()
        else:
            workspace = self.request('/workspaces', {'workspace': {
                'name': self.instance.project, 'description': 'Local scaffold verification',
                'workingDirectory': '/srv/crux-run', 'allowAllCommands': True}})['workspace']
            self.instance.data['agentrq_workspace_id'] = workspace['id']
        token = self.request(self.workspace_path + '/token')['token']
        self.instance.data['agentrq_workspace_token'] = token
        private_write(self.instance.path, json.dumps(self.instance.data, indent=2) + '\n')
        return {'AGENTRQ_WORKSPACE_ID': self.instance.data['agentrq_workspace_id'], 'AGENTRQ_WORKSPACE_TOKEN': token}
