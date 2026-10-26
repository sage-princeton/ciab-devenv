"""Report installed Ubuntu packages without accessing credentials or agent data."""
import json
import platform
import subprocess
from datetime import datetime, timezone


def packages(output):
    result=[]
    for line in output.splitlines():
        fields=line.split('\t')
        if len(fields)!=5 or not all(fields[:3]):
            raise ValueError('Incomplete dpkg package inventory')
        result.append(dict(zip(('name','version','architecture','source','source_version'),fields)))
    return result


def main():
    output=subprocess.check_output(['dpkg-query','-W','-f=${binary:Package}\t${Version}\t${Architecture}\t${source:Package}\t${source:Version}\n'],text=True)
    print(json.dumps({'collected_at':datetime.now(timezone.utc).isoformat(),
        'os':platform.freedesktop_os_release(),'packages':packages(output)},indent=2))


if __name__=='__main__':
    main()
