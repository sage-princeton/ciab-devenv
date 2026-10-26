"""Stage SDK source and select its production configuration."""
from devops.machine_setup import replace_tree, run
from devops.source import source_path


def prepare(settings):
    replace_tree(source_path('/source', 'sdk'), '/opt/crux-sdk-scaffold', preserve=('.venv',))
    run(['chmod', '-R', 'a+rX,go-w', '/opt/crux-sdk-scaffold'])


def settings_environment(settings):
    return {'OPENAI_AGENTS_MODEL': settings['model'], 'OPENAI_AGENTS_REASONING_EFFORT': settings['effort']}


def installed(scaffold):
    pass


def configured(scaffold):
    pass
