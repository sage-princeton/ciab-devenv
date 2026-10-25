"""Stage SDK source and select its production configuration."""
from services.machine_setup import replace_tree, run


def prepare(settings):
    replace_tree('/source/src/sdk-scaffold', '/opt/crux-sdk-scaffold', preserve=('.venv',))
    run(['chmod', '-R', 'a+rX,go-w', '/opt/crux-sdk-scaffold'])


def settings_environment(settings):
    return {'OPENAI_AGENTS_MODEL': settings['model'], 'OPENAI_AGENTS_REASONING_EFFORT': settings['effort']}


def installed(scaffold):
    pass


def configured(scaffold):
    pass
